"""Download verified speaker assets for development or the portable folder."""
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speaker_runtime import (SPEAKER_HASHES, SEGMENTATION_URL,
                             SEGMENTATION_ARCHIVE_HASH, EMBEDDING_URL)


def verified_download(url, expected):
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError(f'Speaker download checksum mismatch: {url}')
    return data


def main(destination):
    root = Path(destination) / 'models' / 'speakers'
    root.mkdir(parents=True, exist_ok=True)
    if not (all((root / name).is_file() and hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
                for name, expected in SPEAKER_HASHES.items())
            and all((root / name).is_file() for name in ('SEGMENTATION_LICENSE', 'SEGMENTATION_README.md'))):
        archive = verified_download(SEGMENTATION_URL, SEGMENTATION_ARCHIVE_HASH)
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:bz2') as tar:
            # Copy only named data files. Never extract archive paths or execute scripts.
            for source, target in (('model.onnx', 'segmentation.onnx'), ('LICENSE', 'SEGMENTATION_LICENSE'), ('README.md', 'SEGMENTATION_README.md')):
                member = tar.extractfile(f'sherpa-onnx-pyannote-segmentation-3-0/{source}')
                if member is None:
                    raise RuntimeError(f'Missing speaker asset: {source}')
                (root / target).write_bytes(member.read())
        (root / 'embedding.onnx').write_bytes(verified_download(EMBEDDING_URL, SPEAKER_HASHES['embedding.onnx']))
    for name, expected in SPEAKER_HASHES.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'Invalid packaged speaker asset: {name}')
    notices = Path(__file__).resolve().parents[1] / 'SPEAKER_MODEL_NOTICES.md'
    (root / 'NOTICES.md').write_bytes(notices.read_bytes())
    (Path(destination) / 'SPEAKER_MODEL_NOTICES.md').write_bytes(notices.read_bytes())
    manifest = {'segmentation_url': SEGMENTATION_URL, 'segmentation_archive_sha256': SEGMENTATION_ARCHIVE_HASH,
                'embedding_url': EMBEDDING_URL, 'sha256': SPEAKER_HASHES}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'Bundled speaker models: {sum((root / name).stat().st_size for name in SPEAKER_HASHES):,} bytes')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'dist/Dubtitler')
