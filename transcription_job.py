"""Isolated transcription: never modifies the editor, source media, or SRT files."""
import math
import os
from audio_tracks import decode_audio_track
from model_runtime import load_model


def run_job(connection, path, model_name, allow_download, audio_index):
    try:
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
        model = load_model(model_name, phase, allow_download)
        phase('Preparing selected audio and detecting speech…', -1)
        segments, info = model.transcribe(audio, language='en', vad_filter=True)
        duration = info.duration
        measured = duration > 0 and math.isfinite(duration)
        phase('Transcribing English audio…', 0 if measured else -1)
        rows, furthest = [], 0.0
        for segment in segments:
            rows.append((round(segment.start * 1000), round(segment.end * 1000), segment.text.strip()))
            furthest = max(furthest, segment.end)
            percent = min(99, int(100 * furthest / duration)) if measured else -1
            detail = f'Audio position {furthest:.1f}s / {duration:.1f}s' if measured else f'{len(rows)} subtitles generated'
            phase(f'Transcribing — {detail}', percent)
        phase('Finishing subtitle list…', -1)
        connection.send(('completed', rows))
    except Exception as exc:
        connection.send(('failed', str(exc)))
    finally:
        connection.close()
