# Offline speaker models

The portable ZIP includes two unmodified ONNX models published by the
[sherpa-onnx project](https://github.com/k2-fsa/sherpa-onnx).
Download URLs and SHA-256 hashes are recorded in `models/speakers/manifest.json`.
The application performs CPU inference locally; it never uploads audio.

## Segmentation

pyannote segmentation 3.0, by CNRS / the pyannote team, converted to ONNX by
sherpa-onnx. Source: https://huggingface.co/pyannote/segmentation-3.0.
License: MIT. The license and conversion README from the original archive are
included as `SEGMENTATION_LICENSE` and `SEGMENTATION_README.md` beside the model.
No changes have been made to the downloaded ONNX model.

## Speaker embeddings

WeSpeaker CAM++, trained on VoxCeleb, converted for sherpa-onnx with model
metadata. Authors: WeSpeaker contributors / wenet-e2e, and the VoxCeleb authors
(Arsha Nagrani, Joon Son Chung, Andrew Zisserman and collaborators).
Source and model list: https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md.
VoxCeleb: https://www.robots.ox.ac.uk/~vgg/data/voxceleb/.
WeSpeaker states that VoxCeleb pretrained weights follow the dataset's
Creative Commons Attribution 4.0 International license (CC BY 4.0):
https://creativecommons.org/licenses/by/4.0/ and
https://creativecommons.org/licenses/by/4.0/legalcode.txt.
Attribution and license links are retained here; no changes have been made
to the downloaded model. The code license is separate from the weights license.

## Runtime

sherpa-onnx is Apache-2.0: https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE.
Its installed notices are copied to the portable `licenses` folder.
