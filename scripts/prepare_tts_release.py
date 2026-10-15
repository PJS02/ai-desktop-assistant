"""Prepare only custom weights/reference for review; never publishes or commits."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from character.tts_models import load_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path, help='Voice Lab export/capstone_tts directory')
    args = parser.parse_args()
    catalog = load_catalog()
    destination = ROOT / 'tts-release' / catalog['version']
    manifest = json.loads((args.export / 'manifest.json').read_text(encoding='utf8'))
    if manifest.get('reference_text') != catalog['reference_text']:
        raise SystemExit('Reference transcript does not match the configured voice.')
    own = [a for a in catalog['assets'] if 'github.com/PJS02/ai-desktop-assistant/releases/' in a['url']]
    # Validate the entire input before writing any release files.
    for asset in own:
        path = args.export / Path(asset['path']).name
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if path.stat().st_size != asset['size'] or digest.hexdigest() != asset['sha256']:
            raise SystemExit('Input does not match the pinned model: ' + path.name)
    destination.mkdir(parents=True, exist_ok=True)
    for asset in own:
        shutil.copy2(args.export / Path(asset['path']).name, destination / Path(asset['path']).name)
    (destination / 'SHA256SUMS').write_text(''.join(a['sha256'] + '  ' + Path(a['path']).name + '\n' for a in own), encoding='utf8')
    shutil.copy2(ROOT / 'tts_runtime/THIRD_PARTY_NOTICES.md', destination / 'THIRD_PARTY_NOTICES.md')
    shutil.copy2(ROOT / 'tts_runtime/vendor/GPT_SoVITS/LICENSE', destination / 'LICENSE-GPT-SoVITS.txt')
    print('Prepared locally:', destination)
    print('Release tag:', 'tts-' + catalog['version'])
    print('Custom assets:', sum(a['size'] for a in own), 'bytes')
    print('Nothing was uploaded. Publish after review, then mark published=true in character/tts_models.json.')


if __name__ == '__main__':
    main()
