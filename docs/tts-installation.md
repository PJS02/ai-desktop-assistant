# GPT-SoVITS / OpenVoice V2

## Windows installer

The full installer ships both models, their private Python runtime, and the Korean text-processing data.
Select a voice under **설정 → 대화·음성 → 목소리**.
Under **설정 → 실행 환경**, select **자동**, **CPU** or **CUDA**, apply, and restart Cloudy.
The two voices use CPU when selected or when the bundled CUDA runtime cannot use the installed GPU.
CUDA inference uses PyTorch 2.0 with CUDA 11.8 and needs a compatible NVIDIA GPU and driver.

## Source checkout setup

1. Use Windows Python 3.10.
2. With the app closed, run `setup_tts_runtime.cmd` once. It creates `.tts-runtime/env`, installs the
   pinned inference libraries and Korean text-processing resources, and checks CPU inference.
3. Open **설정 → 대화·음성 → 음성 모델 다운로드**. Download the desired engine, then select its voice and apply.
   This step downloads model files only; it does not run pip or modify drivers.

Model downloads show progress, can be cancelled and retried, and verify both
length and SHA-256 before atomically replacing a file. A completed receipt is
written only after every required file is verified. Previously completed files
are verified and reused on retry; partial files are removed. Downloads continue
when the settings dialog closes, and reopening it shows the current job.

Source runs save downloaded models in the user's application-data directory under
`PJS02/AIDesktopAssistant/tts-models`. The full Windows installer loads them from `app/models/tts`.
`CAPSTONE_TTS_MODEL_DIR` can override the model location.
The selected voice and enabled state use QSettings.

Supertonic remains available. Additional voices become selectable only after
their models and runtime are ready. Inference runs in a persistent subprocess;
audio playback, speaking/busy notifications and dialogue tracing stay in the
existing application service. Switching voices or cancelling speech discards old
results. App shutdown terminates the owned inference process.

When voice output is enabled, startup prepares the selected model on the existing
background worker. The first utterance
reuses that model; selecting another voice or enabling output prepares it again.
Disabled voice output does not preload a model. Missing custom models still need
to be installed from settings in source runs.

Startup readiness appears as one bar above the character with a percentage beside
it. Hover over the bar for each model/device's status. The percentage averages
confirmed preparation steps across enabled features, rather than estimating time;
tasks without intermediate progress advance when their ready event arrives.
The bar hides three seconds after completion and returns for loading or errors.

**설정 → 대화·음성 → 말풍선 표시 시점** controls when AI response text
appears. It defaults to off (show text immediately). When on, the bubble waits
for the audio device's actual playback-start signal, rather than synthesis
completion. Disabled/unavailable audio and AI error notices still display text.
Turning synchronization off while waiting releases the text immediately. The
setting is applied and saved with the other voice settings.

## Release preparation

The custom voice is published in the
[tts-74107e113436-v1 release](https://github.com/PJS02/ai-desktop-assistant/releases/tag/tts-74107e113436-v1).
The catalog's three custom assets have `published: true`; the settings dialog
downloads them alongside the pinned public base models. A future unpublished
catalog entry must remain `published: false` so the UI displays **배포 준비 중**
instead of offering a broken download.

To prepare the release files locally:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_tts_release.py "<Voice Lab export\capstone_tts>"
```

Review `tts-release/74107e113436-v1`, the input provenance and licensing. The script
does not publish anything. After explicitly authorized publication to the
`tts-74107e113436-v1` GitHub release, verify all three exact asset URLs and hashes,
then change only those catalog entries to `published: true`. This version's
public URLs and downloaded hashes were verified before activation. Do not change the
weights attached to an existing version; create a new version/catalog instead.

Required downloads currently total 1,238,325,787 bytes for GPT-SoVITS and
815,545,678 bytes for OpenVoice V2. Both include the shared 230,444-byte reference;
installing both reuses it. Initial library installation uses additional disk and
network space. These figures describe the catalog, not yet a measured clean-PC
installation footprint.

Local validation on the author's GPU completed fresh-environment synthesis for
both engines. GPT-SoVITS took about 27 seconds for its first request and 2.6 seconds
for the next; OpenVoice V2 took about 19 seconds and 1.5 seconds. These include the
first request's model loading and are measurements on one PC, not guarantees for
other devices. Generated waveforms were nonempty; voice quality still needs
listening review. The initial environment occupied approximately 5.8 GiB during
validation; optional models are additional, and cached installer files can use
more space.

Commit source, dependency specifications, catalog and documentation. Do not
commit `.tts-runtime`, `.tts-models`, `tts-release`, local validation or test files.
