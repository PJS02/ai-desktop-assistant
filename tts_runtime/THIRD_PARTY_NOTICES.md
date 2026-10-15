# Korean TTS inference sources

The application integrates the following projects. Their original copyright
notices and applicable licenses must accompany redistributed sources/models.

* GPT-SoVITS: https://github.com/RVC-Boss/GPT-SoVITS, MIT, copyright 2024 RVC-Boss.
  The vendored inference sources were selected from the Windows v2Pro export
  `74107e113436`. The package also contains upstream components such as BigVGAN;
  preserve their included licenses and notices.
  Apache-2.0 components retain their original source notices; the license text
  is included in `licenses/Apache-2.0.txt`.
* OpenVoice V2: https://github.com/myshell-ai/OpenVoice, MIT, copyright 2024 MyShell.ai.
  See `vendor/OpenVoice/LICENSE`.
* MeloTTS: https://github.com/myshell-ai/MeloTTS, MIT, copyright 2024 MyShell.ai.
  See `vendor/MeloTTS/LICENSE`. The export's Korean lazy imports are retained;
  the Korean BERT directory is supplied by `CAPSTONE_TTS_KOREAN_BERT`.
  Korean G2P reuses GPT-SoVITS's Windows dictionary-path correction; the unused
  eager Chinese import in TextPreprocessor is removed and Chinese Jieba imports
  use the pure-Python package to avoid an unnecessary compiler requirement.

The `vendor` directory contains inference code and supporting text resources,
not model checkpoints, Python interpreters, training datasets or CUDA binaries.
Installed dependencies retain their own licenses in the isolated environment.
Model URLs, upstream revisions, file lengths and SHA-256 values are recorded in
`character/tts_models.json`. Public model assets are retrieved from their original
providers. Before publishing custom assets, confirm the source reference audio,
training data and all relevant base-model terms permit the intended distribution.

No model performance, voice quality or redistribution rights are implied merely
by a package importing successfully.
