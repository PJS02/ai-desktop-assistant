# Cloudy Windows 설치본의 모델 출처

- **Supertonic 3**의 가중치와 기본 음성은 Supertone Inc.의 OpenRAIL-M 라이선스를 따릅니다. 사용 조건 전문은 설치 폴더의 `app/models/supertonic-3/LICENSE`에 있습니다. [모델과 사용 조건](https://huggingface.co/Supertone/supertonic-3)
- **multilingual-e5-small**은 장기기억 임베딩에 사용합니다. 모델 카드는 MIT 라이선스를 명시합니다. [모델 카드](https://huggingface.co/intfloat/multilingual-e5-small)
- **PP-OCRv5_server_det**와 **korean_PP-OCRv5_mobile_rec**은 화면 텍스트 검출과 인식에 사용합니다. PaddlePaddle은 모델을 Apache 2.0으로 제공합니다. [텍스트 검출 모델](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_det) · [한국어 OCR 모델](https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec)
- **KoELECTRA-small-v3-modu-ner**는 한국어 인명을 찾는 데 사용합니다. 제작자 Leo Kang(Leo97)은 출처를 명시한 내부 추론 사용을 허용했습니다. 외부에 설치본을 배포하려면 이 모델의 재배포 허가를 확인하세요. [모델 카드](https://huggingface.co/Leo97/KoELECTRA-small-v3-modu-ner) · [제작자 답변](https://huggingface.co/Leo97/KoELECTRA-small-v3-modu-ner/discussions/3)
- **MediaPipe BlazePose Heavy**는 웹캠 자세 인식에 사용합니다. Apache 2.0 라이선스 전문은 번들 Python의 MediaPipe 라이선스 파일에 있습니다. [MediaPipe 모델 출처](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/models.md) · [MediaPipe 라이선스](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE)
- **GPT-SoVITS** 기본 가중치와 **OpenVoice V2**, **MeloTTS-Korean** 모델 카드는 MIT 라이선스를 명시합니다. 라이선스 전문은 설치본의 `app/tts_runtime/vendor`에서 확인할 수 있습니다. [GPT-SoVITS](https://huggingface.co/lj1995/GPT-SoVITS) · [OpenVoice V2](https://huggingface.co/myshell-ai/OpenVoiceV2) · [MeloTTS-Korean](https://huggingface.co/myshell-ai/MeloTTS-Korean)
- OpenVoice V2의 한국어 언어 모델은 **kykim/bert-kor-base**입니다. 모델 카드에 재배포 라이선스가 명시되어 있지 않습니다. 학습한 음성과 기준 음성은 프로젝트의 TTS 릴리스에서 가져옵니다. [한국어 BERT 모델 카드](https://huggingface.co/kykim/bert-kor-base) · [Cloudy 음성 릴리스](https://github.com/PJS02/ai-desktop-assistant/releases/tag/tts-74107e113436-v1)
- 음성 실행 환경은 PyTorch 2.0과 번들 CUDA 11.8 라이브러리를 사용합니다. [CUDA 11.8 소프트웨어 라이선스](https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html)

## E5 MIT 라이선스

[Microsoft UniLM 라이선스 원문](https://github.com/microsoft/unilm/blob/master/LICENSE)

```text
The MIT License (MIT)

Copyright (c) Microsoft Corporation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
