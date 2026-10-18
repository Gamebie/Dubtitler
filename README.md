# Dubtitler v0.3.0

A local Windows app for creating, editing, and exporting English dub subtitles.

## Use the offline portable app (recommended)

1. Download **Dubtitler-v0.3.0-Windows-Offline-Portable.zip** from a successful
   Actions build, or from the v0.3.0 preview release when published.
2. Right-click the ZIP and **Extract All**. Keep the entire `Dubtitler` folder,
   including `_internal` and `models`. Run `Dubtitler.exe` inside that folder.
   No installer, Python installation, account, or model download is needed.
3. **Choose Video**: select a video, then select its English dub under **Audio track**.
4. **Choose a model and transcribe**: keep **Base English** for offline use and
   click **Transcribe English Dub**. Preview and transcription use the selected
   track. The app initially prefers an English-tagged track; confirm by listening.
5. **Review, edit and export**: double-click cells to edit dialogue or timing
   (`HH:MM:SS,mmm`), select rows to seek, and add/delete rows as needed. Click
   **Export SRT** and save beside your video. Import SRT also works without a video.

The portable ZIP includes one English-only `base.en` model (about 148 MB before
compression). Other models remain optional. There is **no installer artifact in
the v0.2 workflow**; old v0.1 installer/portable downloads do not include this model.
The old Inno Setup script is retained only as a legacy build reference.

## Audio, cancellation and replay (v0.3.0)

- The audio selector lists every audio stream with language, codec, channel count
  and title where available. English tags are preferred, avoiding commentary when
  another English track is tagged. Missing tags fall back to the first track;
  choose manually if needed. No-audio files disable transcription with a message.
- Track selection controls preview and transcription. If Qt cannot match the
  file's audio streams, preview is muted with an explanation; transcription can
  still use the selected stream. Leading track offsets are retained relative to
  the video timeline. Recovery copies also remember the selected track.
- **Cancel transcription** stops the isolated transcription process during audio
  reading, model loading/downloading or recognition. The editor remains open,
  existing subtitles, undo history and recovery files are preserved, and no
  partial transcript replaces them. Wait for **Cancelled** before closing or
  starting again. Previously cached models are kept; interrupted optional model
  downloads may need to resume on the next attempt.
- Select a subtitle and click **Replay selected** or press **F4**. It plays that
  cue once with configurable **Lead / tail** audio (0–5 seconds on each side;
  default 0.5 seconds). Enable **Loop** to repeat until **Stop replay** is clicked.
  Turning Loop off lets the current pass finish. Boundaries clamp to the video.
- Seeking manually, selecting another row, committing an edit, changing tracks,
  or starting transcription stops replay. End-of-video is handled for looping.
  Replay requires a loaded preview and valid subtitle timings. Its boundary
  checks run every 25 ms; final audible boundaries also depend on codec/output
  buffering, so it is a review aid rather than a sample-accurate audio cutter.

## Editing safety

- **Undo / Redo** buttons and the Edit menu cover committed text/timing edits,
  add/delete operations, and replacement by transcription. Use Ctrl+Z to undo
  and Ctrl+Y or Ctrl+Shift+Z to redo. Up to 100 operations are retained during a
  session; starting another video or importing another SRT starts a new history.
- An asterisk in the title and the status indicator identify unsaved edits.
  Closing, changing video, importing SRT, or replacing unsaved subtitles offers
  **Save / Discard / Cancel**. A cancelled or failed export keeps the edits open.
- Recovery copies are saved after 750 ms of idle time following a committed cell
  edit, add/delete, or transcription. Finish a cell edit with Enter or click
  another cell. The status confirms when the recovery copy has been saved.
  Recovery copies preserve raw text, including temporarily invalid timings.
- On restart, choose **Recover edits**, **Discard copy**, or **Later**. Recovery
  restores subtitles and their associated video/SRT paths; undo history begins
  with the recovered session. Missing videos do not prevent editing/exporting.
- Recovery lives locally at `%LOCALAPPDATA%\Dubtitler\recovery`, never in the app
  folder. Each open window owns a separate locked copy. Override the folder with
  `DUBTITLER_RECOVERY_DIR` if needed. Corrupt copies are kept and reported.
- Exporting or undoing back to the saved content removes the recovery copy.
  Choosing Discard on a normal close intentionally removes that window's copy.
  Recovery is not a replacement for exporting SRT, and cannot preserve text still
  being typed in a cell when the process crashes or edits from the last 750 ms.

## Transcription progress and recovery

- Model lookup/loading, optional downloading, and audio preparation/speech
  detection show an **indeterminate** bar: their APIs do not supply a reliable total.
- Transcription shows **audio position reached / full audio duration**, based on
  generated segment timestamps restored to the original video timeline after VAD.
  This is not elapsed time, remaining time, or a percentage of CPU work. Long
  silence can cause jumps or pauses. Unknown duration stays indeterminate.
- The bar stays below 100% until all segments finish and the subtitle list is ready.
  Silence completes with a clear no-speech message.
- While transcribing, changing video/audio/model and subtitle editing are disabled.
  Cancel the job or wait for it to finish before closing. A failed job keeps existing subtitles
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
Compress-Archive -Path dist/Dubtitler -DestinationPath Dubtitler-v0.3.0-Windows-Offline-Portable.zip
```

The workflow builds on pull requests, main pushes, and manual runs. It tests the
extracted ZIP with empty model caches, Hugging Face offline mode, and Python
socket connections blocked. Its frozen-app smoke test opens Qt, verifies the
model manifest, selects the English track of a generated dual-track video, checks
replay/loop control, spawns a real transcription process, cancels and restarts it,
loads the bundled model, runs VAD on silence, and exercises the decoder. It
uploads the portable only after that test passes. A `v0.3.0` tag
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
