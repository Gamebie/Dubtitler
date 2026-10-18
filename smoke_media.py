"""Small generated video fixtures for portable diagnostics (no external FFmpeg)."""
from fractions import Fraction


def make_media(path, arrays=(), rate=16000, starts=None, languages=None):
    import av
    import numpy as np
    starts = starts or [0] * len(arrays)
    languages = languages or ['jpn', 'eng'][:len(arrays)]
    duration = max([2.0] + [start + len(array) / rate for start, array in zip(starts, arrays)])
    with av.open(str(path), 'w') as output:
        video = output.add_stream('mpeg4', rate=10)
        video.width, video.height, video.pix_fmt = 320, 180, 'yuv420p'
        streams = []
        for index, array in enumerate(arrays):
            stream = output.add_stream('pcm_s16le', rate=rate)
            stream.layout = 'mono' if array.ndim == 1 else 'stereo'
            stream.metadata.update(language=languages[index], title='English dub' if languages[index] == 'eng' else 'Original audio')
            streams.append(stream)
        for index in range(round(duration * 10)):
            image = np.full((180, 320, 3), (35, 65, 95), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(image, format='rgb24')
            frame.pts = index
            for packet in video.encode(frame):
                output.mux(packet)
        for packet in video.encode():
            output.mux(packet)
        for stream, array, start in zip(streams, arrays, starts):
            for index in range(0, len(array), 4000):
                samples = np.clip(array[index:index + 4000] * 32767, -32768, 32767).astype(np.int16)
                frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format='s16', layout=stream.layout.name)
                frame.sample_rate = rate
                frame.time_base = Fraction(1, rate)
                frame.pts = index + round(start * rate)
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)
