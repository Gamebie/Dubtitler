"""Local named show settings, locked and atomically saved across app windows."""
import json
import os
from pathlib import Path
from PySide6.QtCore import QLockFile
from recovery import write_snapshot
from transcription_options import normalize_options


def profiles_directory():
    override = os.environ.get('DUBTITLER_PROFILE_DIR')
    return Path(override) if override else Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'Dubtitler' / 'profiles'


class ProfileStore:
    def __init__(self, directory=None):
        self.path = (Path(directory) if directory is not None else profiles_directory()) / 'shows.json'

    def load(self):
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('profiles'), dict):
            raise ValueError('The saved show profiles are invalid. The original file has been kept.')
        result = {}
        for name, options in data['profiles'].items():
            self.validate_name(name)
            result[name] = normalize_options(options)
        return result

    @staticmethod
    def validate_name(name):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('Give the show profile a name of 1–80 characters.')

    def update(self, name, options=None, delete=False):
        self.validate_name(name)
        name = name.strip()
        if not delete:
            options = normalize_options(options)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(self.path) + '.lock')
        lock.setStaleLockTime(30000)
        if not lock.tryLock(0):
            raise OSError('Another window is saving profiles. Try again in a moment.')
        try:
            profiles = self.load()  # Read again under the lock to retain other windows' changes.
            if delete:
                profiles.pop(name, None)
            else:
                profiles[name] = options
            write_snapshot(self.path, {'version': 1, 'profiles': profiles})
            return profiles
        finally:
            lock.unlock()
