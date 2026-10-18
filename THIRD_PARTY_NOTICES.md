# Bundled Whisper model

The Offline Portable ZIP includes Systran's CTranslate2 conversion of OpenAI
Whisper base.en, from https://huggingface.co/Systran/faster-whisper-base.en at
revision 3d3d5dee26484f91867d81cb899cfcf72b96be6c. The model card declares MIT.
The original model is https://huggingface.co/openai/whisper-base.en.
The model card and a manifest of SHA-256 file hashes accompany the model.

## OpenAI Whisper license

MIT License

Copyright (c) 2022 OpenAI

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

## Runtime libraries

The v0.4 portable also includes pyannote segmentation (MIT) and WeSpeaker CAM++
VoxCeleb speaker embeddings (CC BY 4.0), with attribution, source URLs and license
links in `models/speakers/NOTICES.md` (source: `SPEAKER_MODEL_NOTICES.md`). Their
SHA-256 hashes are pinned in `speaker_runtime.py` and the packaged manifest.

The portable runtime also contains PySide6/Qt, faster-whisper, CTranslate2,
PyAV/FFmpeg libraries, ONNX Runtime, tokenizers, and their dependencies.
Their installed license/notice files and a package inventory are copied to the
`licenses` folder by `scripts/collect_licenses.py`. Source and license information:

- https://www.qt.io/licensing/ (Qt/PySide6, LGPL/GPL/commercial)
- https://github.com/SYSTRAN/faster-whisper (MIT)
- https://github.com/OpenNMT/CTranslate2 (MIT)
- https://github.com/PyAV-Org/PyAV (BSD; linked FFmpeg libraries use LGPL/GPL)
- https://github.com/microsoft/onnxruntime (MIT)
- https://github.com/huggingface/tokenizers (Apache-2.0)
- https://github.com/k2-fsa/sherpa-onnx (Apache-2.0)
