"""Korean-only local inference. Invoked by the app's dedicated TTS environment."""
import json
import os
from pathlib import Path
import sys
import traceback
import site

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / 'vendor'
MODE, MODELS = sys.argv[1], Path(sys.argv[2]).resolve()
sys.path[:0] = [str(VENDOR), str(VENDOR / 'GPT_SoVITS'),
                str(VENDOR / 'GPT_SoVITS/eres2net'),
                str(VENDOR / 'MeloTTS'), str(VENDOR / 'OpenVoice')]
for directory in json.loads(os.environ.get('CAPSTONE_TTS_EXTRA_SITE', '[]')):
    site.addsitedir(directory)
os.environ['CAPSTONE_TTS_KOREAN_BERT'] = str(MODELS / 'openvoice_v2/bert')


def send(**value):
    print('CAPSTONE_TTS:' + json.dumps(value, ensure_ascii=False), flush=True)


def load_gpt():
    import torch
    import numpy as np
    import soundfile as sf
    if not torch.cuda.is_available():
        raise RuntimeError('GPT-SoVITS에는 지원되는 NVIDIA GPU와 드라이버가 필요합니다.')
    from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
    model_dir = MODELS / 'gpt_sovits'
    pretrained = model_dir / 'GPT_SoVITS/pretrained_models'
    config = TTS_Config({'custom': {'device': 'cuda:0', 'is_half': True, 'version': 'v2Pro',
        't2s_weights_path': str(model_dir / 'gpt.ckpt'), 'vits_weights_path': str(model_dir / 'sovits.pth'),
        'bert_base_path': str(pretrained / 'chinese-roberta-wwm-ext-large'),
        'cnhuhbert_base_path': str(pretrained / 'chinese-hubert-base')}})
    model = TTS(config)
    reference = str(MODELS / 'common/reference.wav')
    model.set_ref_audio(reference)
    def synthesize(text, output):
        chunks = list(model.run({'text': text, 'text_lang': 'ko', 'ref_audio_path': reference,
            'prompt_text': '안녕하세요. 저는 오늘 여러분께 새로운 소식을 전해 드리겠습니다.',
            'prompt_lang': 'ko', 'text_split_method': 'cut5', 'batch_size': 1,
            'parallel_infer': False, 'seed': 42}))
        if not chunks:
            raise RuntimeError('생성된 음성이 없습니다.')
        sf.write(output, np.concatenate([audio for _, audio in chunks]), chunks[0][0], subtype='PCM_16')
    return synthesize


def load_openvoice():
    import torch
    import soundfile as sf
    from melo.api import TTS
    from melo.text import japanese_bert, korean
    from openvoice.api import ToneColorConverter
    from transformers import AutoModelForMaskedLM, AutoTokenizer
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    folder = MODELS / 'openvoice_v2'
    converter = ToneColorConverter(str(folder / 'converter/config.json'), device=device, enable_watermark=False)
    converter.load_ckpt(str(folder / 'converter/checkpoint.pth'))
    model = TTS(language='KR', device=device, use_hf=False,
                config_path=str(folder / 'melo/config.json'), ckpt_path=str(folder / 'melo/checkpoint.pth'))
    bert_id = korean.model_id
    japanese_bert.models[bert_id] = AutoModelForMaskedLM.from_pretrained(bert_id, local_files_only=True).to(device).eval()
    japanese_bert.tokenizers[bert_id] = AutoTokenizer.from_pretrained(bert_id, local_files_only=True)
    korean.korean_text_to_phonemes('안녕하세요')
    source = torch.load(folder / 'kr.pth', map_location=device)
    with torch.autocast(device_type='cuda', dtype=torch.float16, enabled=device.startswith('cuda')):
        target = converter.extract_se(str(MODELS / 'common/reference.wav'))
    def synthesize(text, output):
        temporary = Path(output).with_suffix('.source.wav')
        try:
            audio = model.tts_to_file(text, model.hps.data.spk2id['KR'], output_path=None, speed=1.0, quiet=True)
            sf.write(str(temporary), audio, model.hps.data.sampling_rate)
            with torch.autocast(device_type='cuda', dtype=torch.float16, enabled=device.startswith('cuda')):
                converted = converter.convert(audio_src_path=str(temporary), src_se=source, tgt_se=target,
                                               output_path=None, message='@MyShell')
            sf.write(output, converted, converter.hps.data.sampling_rate, subtype='PCM_16')
        finally:
            temporary.unlink(missing_ok=True)
    return synthesize


def main():
    if MODE not in ('gpt_sovits', 'openvoice_v2'):
        raise ValueError('Unknown engine')
    synthesize = load_gpt() if MODE == 'gpt_sovits' else load_openvoice()
    send(status='ready')
    for line in sys.stdin:
        try:
            request = json.loads(line)
            synthesize(request['text'], request['output'])
            send(status='done')
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            send(error=str(exc))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        send(error=str(exc))
        raise SystemExit(1)
