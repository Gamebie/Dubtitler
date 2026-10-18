# Dubtitler v0.2

A local Windows app for creating, editing, and exporting English dub subtitles.

## Use the offline portable app (recommended)

1. Download **Dubtitler-v0.2.0-Windows-Offline-Portable.zip** from a successful
   Actions build, or from the v0.2.0 preview release when published.
2. Right-click the ZIP and **Extract All**. Keep the entire `Dubtitler` folder,
   including `_internal` and `models`. Run `Dubtitler.exe` inside that folder.
   No installer, Python installation, account, or model download is needed.
3. **Choose Video**: select a video containing English dub audio.
4. **Choose a model and transcribe**: keep **Base English** for offline use and
   click **Transcribe English Dub**. The app uses the first audio stream; for
   multi-track videos, make the English track the first track in your source.
5. **Review, edit and export**: double-click cells to edit dialogue or timing
   (`HH:MM:SS,mmm`), select rows to seek, and add/delete rows as needed. Click
   **Export SRT** and save beside your video. Import SRT also works without a video.

The portable ZIP includes one English-only `base.en` model (about 148 MB before
compression). Other models remain optional. There is **no installer artifact in
the v0.2 workflow**; old v0.1 installer/portable downloads do not include this model.
The old Inno Setup script is retained only as a legacy build reference.

## Progress and recovery

- Model lookup/loading, optional downloading, and audio preparation/speech
  detection show an **indeterminate** bar: their APIs do not supply a reliable total.
- Transcription shows **audio position reached / full audio duration**, based on
  generated segment timestamps restored to the original video timeline after VAD.
  This is not elapsed time, remaining time, or a percentage of CPU work. Long
  silence can cause jumps or pauses. Unknown duration stays indeterminate.
- The bar stays below 100% until all segments finish and the subtitle list is ready.
  Silence completes with a clear no-speech message.
- While transcribing, changing video/model and subtitle editing are disabled.
  Wait for the job to finish before closing. A failed job keeps existing subtitles
  and re-enables controls so you can retry.

## Model locations and optional downloads

The app checks `models/<model name>` beside `Dubtitler.exe` (or `main.py` when run
from source). All required assets, including `tokenizer.json`, must be present so
loading never silently fetches a tokenizer from the internet.

If a bundle is absent/incomplete, it checks the persistent cache at
`%LOCALAPPDATA%\Dubtitler\models`, then the existing Hugging Face cache (including
pre-v0.2 downloads). Override the app cache with `DUBTITLER_MODEL_CACHE` if needed.
Nothing is written into the executable folder during normal transcription.

**Allow a one-time download** is off by default. Enable it for missing optional
models or source installs. A completed download is reused on subsequent jobs.
Offline/cache errors explain how to retry; a corrupt bundled model asks you to
extract the full Offline ZIP again. No video or audio is uploaded for transcription.
CPU int8 inference is used; larger models need more time and memory.

## Run from source

Use 64-bit Python 3.12 on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

To prepare the offline model beside `main.py` once (internet required):

```powershell
python scripts/bundle_model.py .
```

Transcription uses PyAV's bundled FFmpeg libraries, so a separate `ffmpeg.exe`
is not needed. Video preview support depends on Qt/system codecs. Check dialogue,
names, overlapping speech, and timing manually; this transcribes spoken English
and does not translate non-English audio.

## Validate and build

```powershell
pip install -r requirements-build.txt
python -m unittest discover -s tests -v
pyinstaller --noconfirm --clean --windowed --onedir --name Dubtitler --collect-all faster_whisper --collect-all ctranslate2 --collect-all tokenizers --collect-all onnxruntime main.py
python scripts/bundle_model.py dist/Dubtitler
python scripts/collect_licenses.py dist/Dubtitler
Copy-Item README.md,THIRD_PARTY_NOTICES.md dist/Dubtitler/
Compress-Archive -Path dist/Dubtitler -DestinationPath Dubtitler-v0.2.0-Windows-Offline-Portable.zip
```

The workflow builds on pull requests, main pushes, and manual runs. It tests the
extracted ZIP with empty model caches, Hugging Face offline mode, and Python
socket connections blocked. Its frozen-app smoke test opens Qt, verifies the
model manifest, loads the bundled model, runs VAD on silence, and exercises the
decoder. It uploads the portable only after that test passes. A `v0.2.0` tag
publishes a preview release after the build passes; ordinary pushes do not
rewrite an existing release. CI does not replace manual playback and real-video
quality testing on another Windows PC.

For a local frozen smoke test (writes JSON because the app has no console):

```powershell
$p = Start-Process dist/Dubtitler/Dubtitler.exe -ArgumentList '--smoke-test', 'smoke-result.json' -Wait -PassThru -WindowStyle Hidden
Get-Content smoke-result.json
```

An optional WAV path after the result path also tests real speech transcription.
See `THIRD_PARTY_NOTICES.md` for the bundled model source and license.
