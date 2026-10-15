"""One-time Korean inference environment setup; model downloads live in Settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / '.tts-runtime'


def run(python, *args):
    subprocess.run([str(python), '-X', 'utf8', *args], cwd=ROOT, check=True,
                   env=dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
                            NLTK_DATA=str(HOME / 'nltk_data')))


def main():
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 10):
        raise SystemExit('Windows Python 3.10 is required for this pinned TTS environment.')
    HOME.mkdir(exist_ok=True)
    # Never report a partly installed/upgraded environment as ready.
    (HOME / 'runtime.json').unlink(missing_ok=True)
    environment = HOME / 'env'
    python = environment / 'Scripts/python.exe'
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    run(python, '-m', 'pip', 'install', 'pip==25.0.1', 'setuptools==69.5.1', 'wheel==0.45.1')
    run(python, '-m', 'pip', 'install', 'torch==2.0.0+cu118', 'torchaudio==2.0.1+cu118',
        '--index-url', 'https://download.pytorch.org/whl/cu118')
    run(python, '-m', 'pip', 'install', '-r', str(ROOT / 'tts_runtime/requirements.txt'),
        '-c', str(ROOT / 'tts_runtime/constraints.txt'))
    run(python, '-m', 'nltk.downloader', '-d', str(HOME / 'nltk_data'),
        'cmudict', 'averaged_perceptron_tagger')
    run(python, '-c', 'import torch, torchaudio, transformers, peft, librosa, soundfile, g2pk2; '
        'print("CUDA available:", torch.cuda.is_available()); '
        'assert torch.cuda.is_available(), "A supported NVIDIA GPU/driver is required"')
    vendor = ROOT / 'tts_runtime/vendor'
    run(python, '-c', 'import sys;sys.path[:0]=' + repr([str(vendor), str(vendor / 'GPT_SoVITS'),
        str(vendor / 'GPT_SoVITS/eres2net'), str(vendor / 'MeloTTS'), str(vendor / 'OpenVoice')])
        + ';from GPT_SoVITS.TTS_infer_pack.TTS import TTS;import melo.api,openvoice.api;'
        + 'print("Inference imports ready")')
    temporary = HOME / 'runtime.tmp'
    temporary.write_text(json.dumps({'python': str(python.resolve()), 'format': 1}), encoding='utf8')
    temporary.replace(HOME / 'runtime.json')
    print('Ready. Download GPT-SoVITS / OpenVoice V2 from Settings > Voice.')


if __name__ == '__main__':
    main()
