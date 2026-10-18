"""Model discovery shared by the desktop app and the portable build checks."""
import os
import sys
from pathlib import Path

DEFAULT_MODEL = 'base.en'
BUNDLE_REPO = 'Systran/faster-whisper-base.en'
BUNDLE_REVISION = '3d3d5dee26484f91867d81cb899cfcf72b96be6c'
MODEL_FILES = ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt')


def app_directory():
    # Models live beside the executable, outside PyInstaller's _internal folder.
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def complete_model(path):
    def present(name):
        file = Path(path) / name
        return file.is_file() and file.stat().st_size > 0
    return all(present(name) for name in MODEL_FILES[:3]) and any(present(name) for name in ('vocabulary.txt', 'vocabulary.json'))


def bundled_model(name):
    path = app_directory() / 'models' / name
    return path if complete_model(path) else None


def cache_directory():
    # Never write into the portable app folder, which may be read-only.
    override = os.environ.get('DUBTITLER_MODEL_CACHE')
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'Dubtitler' / 'models'


def load_model(name, phase, allow_download=False):
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    local = bundled_model(name)
    if local:
        phase(f'Loading bundled {name} model — offline', -1)
        try:
            return WhisperModel(str(local), device='cpu', compute_type='int8', local_files_only=True)
        except Exception as exc:
            # A corrupt bundle should not silently turn into a network download.
            raise RuntimeError(f'Could not load bundled model at {local}. Extract the full Offline ZIP again. {exc}') from exc

    phase(f'Looking for cached {name} model…', -1)
    roots = (str(cache_directory()), None)  # Also reuse pre-v0.2 Hugging Face caches.
    for root in roots:
        try:
            path = download_model(name, cache_dir=root, local_files_only=True)
        except Exception:
            continue
        if complete_model(path):
            phase(f'Loading cached {name} model — offline', -1)
            return WhisperModel(path, device='cpu', compute_type='int8', local_files_only=True)

    if not allow_download:
        raise RuntimeError(f'{name} is not available locally. Use the full Offline ZIP or enable the one-time model download in step 2.')
    phase(f'Downloading {name} model once — internet required; size is not reported', -1)
    path = download_model(name, cache_dir=str(cache_directory()))
    if not complete_model(path):
        raise RuntimeError('The downloaded model is incomplete. Check the connection and retry.')
    phase(f'Loading downloaded {name} model…', -1)
    return WhisperModel(path, device='cpu', compute_type='int8', local_files_only=True)
