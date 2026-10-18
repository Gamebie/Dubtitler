"""Preserve installed runtime packages' license/notice files in the ZIP."""
import json
import shutil
import sys
from importlib.metadata import distributions
from pathlib import Path


def main(destination):
    target = Path(destination) / 'licenses'
    packages = []
    for distribution in distributions():
        name = distribution.metadata['Name']
        if name.lower() in {'pip', 'setuptools', 'pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph', 'pefile', 'pywin32-ctypes'}:
            continue
        packages.append({'name': name, 'version': distribution.version})
        for file in distribution.files or []:
            # Match individual license files, not arbitrary paths outside the package.
            if not any(word in file.name.lower() for word in ('license', 'copying', 'notice')):
                continue
            source = distribution.locate_file(file)
            if source.is_file():
                output = target / name / Path(*[part for part in file.parts if part not in ('.', '..')])
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, output)
    target.mkdir(parents=True, exist_ok=True)
    (target / 'packages.json').write_text(json.dumps(sorted(packages, key=lambda p: p['name']), indent=2), encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'dist/Dubtitler')
