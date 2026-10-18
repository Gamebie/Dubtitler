"""Run as Dubtitler.exe --smoke-test RESULT.json [speech.wav]."""
import hashlib
import json
import os
import socket
import traceback
import tempfile
import wave
from pathlib import Path


def run(args):
    result_path = Path(args[0]) if args else Path('smoke-result.json')
    result = {'ok': False}
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

    def no_network(*_):
        raise RuntimeError('Network attempted during offline smoke test')

    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    try:
        import numpy as np
        from PySide6.QtWidgets import QApplication
        from main import MainWindow
        from model_runtime import DEFAULT_MODEL, bundled_model, load_model
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.show()
        app.processEvents()
        assert not window.transcribe_button.isEnabled()
        assert not window.export_button.isEnabled()
        window.add_row()
        assert window.export_button.isEnabled()
        window.close()
        path = bundled_model(DEFAULT_MODEL)
        if path is None:
            raise RuntimeError('Offline portable is missing its complete bundled model')
        manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['sha256'].items():
            assert hashlib.sha256((path / name).read_bytes()).hexdigest() == expected, name
        model = load_model(DEFAULT_MODEL, lambda *_: None, allow_download=False)
        # Use a file, not just an array: this also tests bundled PyAV/FFmpeg.
        with tempfile.TemporaryDirectory() as temp:
            silence_path = str(Path(temp) / 'silence.wav')
            with wave.open(silence_path, 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\0\0' * 16000)
            segments, _ = model.transcribe(silence_path, language='en', vad_filter=True)
            assert list(segments) == [], 'Silence generated subtitles'
        # Exercise decoding as well as the VAD no-speech path.
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language='en', vad_filter=False)
        list(segments)
        result.update(ok=True, model=str(path), revision=manifest['revision'], silence=True)
        if len(args) > 1:
            segments, _ = model.transcribe(args[1], language='en', vad_filter=True)
            text = ' '.join(s.text.strip() for s in segments)
            if not text:
                raise RuntimeError('Speech fixture produced no transcription')
            result['speech_text'] = text
    except Exception:
        result.update(ok=False, error=traceback.format_exc())
    result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
