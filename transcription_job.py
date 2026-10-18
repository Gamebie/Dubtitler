"""Isolated transcription: never modifies the editor, source media, or SRT files."""
import math
import os
from audio_tracks import decode_audio_track
from model_runtime import load_model
from speaker_runtime import detect_speaker_turns
from subtitle_timing import make_cues
from transcription_options import normalize_options, recognition_hints, correct_text


def detect_speech(audio):
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    regions = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=250, speech_pad_ms=80))
    return [(region['start'] / 16000, region['end'] / 16000) for region in regions]


def run_job(connection, path, model_name, allow_download, audio_index, options=None):
    try:
        options = normalize_options(options)
        if os.environ.get('DUBTITLER_OFFLINE_TEST') == '1':
            import socket
            def no_network(*_):
                raise RuntimeError('Network attempted in offline transcription test')
            socket.socket.connect = no_network
            socket.socket.connect_ex = no_network
        def phase(message, value):
            connection.send(('progress', message, value))
        phase(f'Reading audio track {audio_index + 1}…', -1)
        audio = decode_audio_track(path, audio_index)
        phase('Detecting speech and quiet gaps…', -1)
        speech_regions = detect_speech(audio)
        if not speech_regions:
            connection.send(('completed', []))
            return
        turns = detect_speaker_turns(audio, phase) if options['speaker_changes'] else []
        model = load_model(model_name, phase, allow_download)
        phase('Preparing selected audio and detecting speech…', -1)
        segments, info = model.transcribe(
            audio, language='en', vad_filter=True, word_timestamps=True,
            vad_parameters={'min_silence_duration_ms': 250, 'speech_pad_ms': 80},
            hallucination_silence_threshold=1.0, **recognition_hints(options))
        duration = info.duration
        measured = duration > 0 and math.isfinite(duration)
        phase('Transcribing English audio…', 0 if measured else -1)
        aligned, furthest = [], 0.0
        for segment in segments:
            aligned.append(segment)
            furthest = max(furthest, segment.end)
            percent = min(99, int(100 * furthest / duration)) if measured else -1
            detail = f'Audio position {furthest:.1f}s / {duration:.1f}s' if measured else f'{len(aligned)} segments recognized'
            phase(f'Transcribing — {detail}', percent)
        phase('Timing subtitles to speech, voice changes and quiet gaps…', -1)
        rows = [(start, end, correct_text(text, options)) for start, end, text in make_cues(aligned, speech_regions, turns)]
        connection.send(('completed', rows))
    except Exception as exc:
        connection.send(('failed', str(exc)))
    finally:
        connection.close()
