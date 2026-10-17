# Dubtitler

A local Windows desktop app for generating English dub subtitles from video, reviewing/editing subtitle timing and text, and exporting SRT.

## Windows setup

1. Install Python 3.11 or 3.12 (64-bit) and add it to PATH.
2. Install [FFmpeg](https://ffmpeg.org/download.html) and ensure `ffmpeg` is on PATH (required by faster-whisper for some inputs; video playback depends on system codecs).
3. Open PowerShell in this directory and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

The first transcription downloads a Whisper model. Subsequent runs use the cached model. CPU transcription may take some time.

## Features

- Open a local MP4/MKV video (playback support varies with Qt Multimedia codecs)
- Play/pause and seek
- Transcribe English audio locally with faster-whisper
- Edit, insert and delete subtitles in a table
- Click a subtitle row to seek the video
- Overlay the current subtitle over the player
- Import/export standard SRT subtitles

## Notes

This is an initial prototype, not a signed Windows installer. Transcription is CPU-based by default. Check the output manually, especially names, overlapping speech and background music. Only process media you have permission to use.
