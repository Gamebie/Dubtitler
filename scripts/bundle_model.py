"""Download only the pinned English model assets."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_runtime import BUNDLE_REPO, BUNDLE_REVISION, DEFAULT_MODEL, MODEL_FILES, complete_model


def main(destination):
    from huggingface_hub import hf_hub_download
    target = Path(destination) / 'models' / DEFAULT_MODEL
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in (*MODEL_FILES, 'README.md'):
        source = hf_hub_download(BUNDLE_REPO, name, revision=BUNDLE_REVISION)
        output = target / name
        shutil.copy2(source, output)
        hashes[name] = hashlib.sha256(output.read_bytes()).hexdigest()
    if not complete_model(target):
        raise RuntimeError('Bundled model is incomplete')
    manifest = {'repo': BUNDLE_REPO, 'revision': BUNDLE_REVISION, 'sha256': hashes}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'Bundled {DEFAULT_MODEL}: {sum(p.stat().st_size for p in target.iterdir()):,} bytes')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'dist/Dubtitler')
