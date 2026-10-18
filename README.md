# Dubtitler v0.6.0

A local Windows app for creating, editing, and exporting English dub subtitles.

## Use the offline portable app (recommended)

1. Download **Dubtitler-v0.6.0-Windows-Offline-Portable.zip** from a successful
   Actions build, or from the v0.6.0 preview release when published.
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
compression), plus neural speaker models (about 35 MB). Other transcription models remain optional. There is **no installer artifact in
the v0.4 workflow**; old v0.1 installer/portable downloads do not include this model.
The old Inno Setup script is retained only as a legacy build reference.

## Projects, waveform and episode queues (v0.6.0)

**Show context / model options** reveals the show/profile, name hints, spelling
rules and download controls. These details start folded to leave room for the
video and waveform during editing; the selected settings remain active.

- Choosing a real video or importing an SRT starts a local **autosaved project**.
  **File → Recent projects** reopens its raw subtitle edits, SRT export baseline,
  video path, selected audio track, show settings/profile, model and playback
  position. Edits/settings save after 750 ms of idle time; playback position saves
  at most every two seconds. Finish an active cell edit to commit it. Autosaves
  live in `%LOCALAPPDATA%\Dubtitler\workspace\projects`; `DUBTITLER_WORKSPACE_DIR`
  overrides the workspace. Project status is shown separately from SRT/recovery
  status. Saving a project does not mark an SRT as exported.
- **Ctrl+S / File → Save project…** saves a named `.dubtitler` file with continuing
  autosave. **Ctrl+O** opens one. Project files contain local paths and settings,
  not a copy of your video. Missing videos leave the subtitles editable; use
  **File → Relink project video…** to restore preview without clearing cues.
  Reopening starts fresh undo history. A project can be open in one window at a
  time; failed writes retain the previous file and show a persistent save error.
  Close flushes the project, then retains the existing SRT Save/Discard/Cancel
  prompt. Discarding an SRT/recovery copy does not delete the autosaved project.
- The **waveform** is decoded from the selected track in an isolated cancellable
  process. It shows audio amplitude (including music), not AI speech labels.
  Choose 5–120 seconds of zoom; it follows the playhead. Click to seek, or select
  a cue and drag a gold start/end edge. A drag is one undoable edit; invalid timing
  is rejected. It does not automatically snap to speech or change text. Changing
  tracks cancels stale waveform work. Preview/seek support still depends on codecs.
- **Navigate** supplies **Ctrl+Up / Ctrl+Down** for previous/next cue, **Ctrl+E**
  to edit current dialogue, **Alt+Up / Alt+Down** to edit previous/next dialogue,
  and **F6** to replay the current cue (**F4** also remains). Navigation commits
  the pending edit and wraps at the ends of the list.
- **Checks / Next warning** now also flag overlapping cues (including nested
  overlaps), possible repeated text within 500 ms, and gaps of at least three
  seconds. Gaps may be intentional silence. All checks are advisory: no automatic
  filling, deletion or timing repair is performed, and valid cues still export.
- **Export SRT** remembers the folder and per-video filename, appends `.srt` when
  no extension is supplied, and asks before overwriting an existing file. The
  source video and open project cannot be replaced by an SRT. Failed/cancelled
  exports retain unsaved state. Existing atomic SRT writing is preserved.
- **Ctrl+B / File → Batch episodes…** queues videos with the current settings or
  a saved show profile. Choose an output folder and start; jobs run sequentially
  in isolated processes. **Auto English** requires an English-tagged track and
  avoids commentary where another tagged track exists. For untagged files,
  choose a numbered track explicitly. Model and optional-download choices are
  copied from the editor when starting. Current editor subtitles are untouched.
  Each spoken result gets its own SRT; existing/same-name files get `_2`, `_3`,
  etc. without overwriting. Silence creates no SRT. Failures are shown per row
  and do not stop later jobs; Start retries rows without completed exports.
  Cancel/close stops the active child, keeps completed exports, leaves remaining
  rows queued, and ignores late results. The queue is session-only, not persisted
  across restarts. Review generated SRTs before use.

## Manual editing tools (introduced in v0.5.0)

All tools work locally. Each replacement, timing change, split, merge or rule
application is one undoable operation, with normal recovery and SRT export.

- **Find / replace** (`Ctrl+H`) searches dialogue with a live match count, whole
  words (on by default) and optional case matching. Find next cycles through
  matching cues. Replace all applies literal text, including punctuation and
  Unicode, to every matching cue; timestamps are untouched. A blank replacement
  removes matches. `Ctrl+Z` undoes the entire replacement.
  **Remember this correction in a show profile…** adds the current whole-word,
  case-insensitive correction to “Always replace” and opens the profile manager
  to save it. Remembering a rule does not replace existing subtitle text.
- **Profiles…** saves the current context, names, “Always replace” spelling rules,
  and voice-change setting under a show name. Choose a saved show in the context
  dropdown before another episode. Add a recurring rule such as
  `say joe => Seijou` in **Always replace**, then save your profile. Loading a
  profile leaves existing cues alone; **Apply current spelling rules to existing
  subtitles** in the profile dialog applies the current rules as one undoable edit.
  Save offers confirmation before overwriting a profile. Delete removes only the
  saved profile, keeping current settings/subtitles. Profiles are stored at
  `%LOCALAPPDATA%\Dubtitler\profiles\shows.json`, with atomic saves and a lock for
  multiple windows. `DUBTITLER_PROFILE_DIR` overrides this directory.
- In **Subtitle tools**, **Set start to playhead** (`Ctrl+Alt+S`) and **Set end to
  playhead** (`Ctrl+Alt+E`) adjust one selected cue. Load a video first. Invalid
  start/end order is rejected. **Shift timing…** (`Ctrl+Shift+T`) moves all cues or
  selected rows by milliseconds: positive means later; negative means earlier.
  A negative/invalid resulting cue cancels the whole shift, without clamping.
- **Split at playhead…** (`Ctrl+Shift+S`) requires one selected cue and a playhead
  strictly inside it. The dialog suggests a text boundary; click or move the text
  cursor to choose exactly where to split. Every original character is retained
  across the two parts. **Merge selected** (`Ctrl+M`) joins consecutive rows in
  timeline order, retaining their outer time range and text separated by newlines.
  Merge can intentionally bridge a quiet gap; replay the result before exporting.
- **Readability** highlights cues and supplies hover explanations for fast reading
  (over 20 non-space characters/second), a display shorter than 0.7 seconds, lines
  longer than 42 characters, more than two lines, or invalid timing. **Next warning**
  cycles through these cues. These are review guides, not universal subtitle
  standards; readability warnings never block export. Invalid timings still do.
- **Drag and drop** one video, one SRT, or a video/SRT pair onto the window. SRTs
  are validated before replacing the current document; normal Save/Discard/Cancel
  protection applies. Multiple videos/SRTs, folders, remote URLs and unsupported
  file types are rejected. Drops wait until transcription or track reading ends.

## Speech timing, voice changes and names (introduced in v0.4.0)

- Recognition now aligns individual words. New cues start at detected speech
  regions, pauses of 350 ms or more between words, detected speaker changes,
  and readability limits of 6 seconds / 84 characters. Cues end at the final
  aligned word rather than staying visible until the next line. Speech detection
  uses 250 ms minimum quiet gaps and 80 ms boundary padding. These are model
  estimates, not sample-accurate boundaries; very short pauses may stay in a cue.
- **Split at voice changes** uses offline pyannote segmentation and WeSpeaker
  CAM++ embeddings through sherpa-onnx. It adds analysis time before recognition.
  It starts a new subtitle for an estimated speaker turn, without guessing a
  character's name or adding speaker labels to your dialogue/SRT. Overlapping
  voices, shouting, music and short replies can cause missed or false changes.
  Turn it off to use speech/word timing without speaker analysis. Missing or
  damaged speaker models produce a clear error; they never download silently.
- Choose **Haikyuu — Seijou**, or enter the show's context and comma-separated
  **Names / terms** yourself. These hints bias recognition toward spellings such
  as **Seijou** rather than “say Joe.” They are optional and may still be wrong.
  This version transcribes English dub audio; it does not translate Japanese.
- **Always replace** is an optional explicit correction list, for example
  `say joe => Seijou; other heard spelling => Correct Name`. Matching is literal,
  case-insensitive and uses whole-word boundaries within a generated cue. These
  rules always apply, so add only errors you want replaced even when those words
  could be legitimate dialogue. The preset supplies hints, with no automatic
  replacement rules. Importing or editing an SRT does not apply these rules.
- Generated subtitles remain one undoable replacement, with all existing editing,
  replay, cancellation, recovery and SRT features. Recovery snapshots also retain
  the context/name settings present when the recovery copy was saved.

The extra speaker weights occupy about 35 MB before ZIP compression and include
source URLs, licenses and pinned SHA-256 hashes. See `SPEAKER_MODEL_NOTICES.md`.

## Audio, cancellation and replay (introduced in v0.3.0)

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

- Voice-change analysis reports processed analysis windows / total windows for that
  phase. Clustering and final subtitle assembly stay indeterminate.
- Model lookup/loading, optional downloading, and audio preparation/speech
  detection show an **indeterminate** bar: their APIs do not supply a reliable total.
- Transcription shows **audio position reached / full audio duration**, based on
  generated segment timestamps restored to the original video timeline after VAD.
  This is not elapsed time, remaining time, or a percentage of CPU work. Long
  silence can cause jumps or pauses. Unknown duration stays indeterminate.
- Each measured phase stays below 100%; only the finished subtitle list shows completion.
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
python scripts/bundle_speakers.py .
```

Transcription uses PyAV's bundled FFmpeg libraries, so a separate `ffmpeg.exe`
is not needed. Video preview support depends on Qt/system codecs. Check dialogue,
names, overlapping speech, and timing manually; this transcribes spoken English
and does not translate non-English audio.

## Validate and build

```powershell
pip install -r requirements-build.txt
python -m unittest discover -s tests -v
pyinstaller --noconfirm --clean --windowed --onedir --name Dubtitler --collect-all faster_whisper --collect-all ctranslate2 --collect-all tokenizers --collect-all onnxruntime --collect-all sherpa_onnx main.py
python scripts/bundle_model.py dist/Dubtitler
python scripts/bundle_speakers.py dist/Dubtitler
python scripts/collect_licenses.py dist/Dubtitler
Copy-Item README.md,THIRD_PARTY_NOTICES.md dist/Dubtitler/
Compress-Archive -Path dist/Dubtitler -DestinationPath Dubtitler-v0.6.0-Windows-Offline-Portable.zip
```

The workflow builds on pull requests, main pushes, and manual runs. It tests the
extracted ZIP with empty model caches, Hugging Face offline mode, and Python
socket connections blocked. Its frozen-app smoke test opens Qt, verifies the
model manifests, runs the offline neural speaker detector on silence, checks word-level
voice/silence splitting and context rules, selects the English track of a generated dual-track video, checks
replay/loop control, spawns a real transcription process, cancels and restarts it,
loads the bundled model, runs VAD on silence, and exercises the decoder. It
uploads the portable only after that test passes. A `v0.6.0` tag
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
