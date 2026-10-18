"""Probe and decode an explicit audio-stream ordinal with PyAV."""
import io


def list_audio_tracks(path):
    import av
    with av.open(path, metadata_errors='ignore') as container:
        return [dict(index=index, stream_index=stream.index,
                     language=stream.metadata.get('language', ''),
                     title=stream.metadata.get('title', ''),
                     codec=stream.codec_context.name or 'unknown',
                     channels=stream.codec_context.channels)
                for index, stream in enumerate(container.streams.audio)]


def default_audio_track(tracks):
    english = [track for track in tracks if track['language'].lower().replace('_', '-').split('-')[0] in ('en', 'eng', 'english')]
    preferred = [track for track in english if 'commentary' not in track['title'].lower()]
    return (preferred or english or tracks)[0]['index'] if tracks else None


def decode_audio_track(path, audio_index):
    import av
    import numpy as np
    if not isinstance(audio_index, int) or audio_index < 0:
        raise ValueError('Choose an audio track before transcribing.')
    buffer = io.BytesIO()
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
    offset = 0.0
    with av.open(path, metadata_errors='ignore') as container:
        if audio_index >= len(container.streams.audio):
            raise ValueError('The selected audio track is no longer available. Reopen the video.')
        origin = float(container.start_time / av.time_base) if container.start_time is not None else 0.0
        first = True
        frames = iter(container.decode(audio=audio_index))
        while True:
            try:
                frame = next(frames)
            except StopIteration:
                break
            except av.error.InvalidDataError:
                continue
            if first:
                if frame.pts is not None:
                    offset = float(frame.pts * frame.time_base) - origin
                first = False
            frame.pts = None
            for converted in resampler.resample(frame):
                buffer.write(converted.to_ndarray().tobytes())
        for converted in resampler.resample(None):
            buffer.write(converted.to_ndarray().tobytes())
    samples = np.frombuffer(buffer.getbuffer(), dtype=np.int16).astype(np.float32) / 32768.0
    if not samples.size:
        raise ValueError('The selected audio track contains no decodable audio.')
    # Preserve leading track offsets relative to the video's normalized timeline.
    shift = round(offset * 16000)
    if shift > 0:
        samples = np.pad(samples, (shift, 0))
    elif shift < 0:
        samples = samples[-shift:]
    if not samples.size:
        raise ValueError('The selected audio track ends before the video starts.')
    return samples
