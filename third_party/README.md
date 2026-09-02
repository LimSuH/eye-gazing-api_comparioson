# Bundled upstream files

The app uses prebuilt browser files; running this project does not require npm,
webpack or a JavaScript build. The original npm archive is included for source,
attribution and offline file restoration. No upstream browser/model bytes were
modified. First-party adapters control calibration/camera/online learning as
described in `THIRD_PARTY_NOTICES.md`.

| Files | Source | Verification |
| --- | --- | --- |
| `sources/webgazer-3.5.3.tgz` | https://registry.npmjs.org/webgazer/-/webgazer-3.5.3.tgz | npm SHA-512: `i6P97fWeixASmHWrJxgLUICugqV6qljIafi2ne6p0WYXAuldpwoaFRkedKFcu/qm95d128gdUxhOr336estXOw==` |
| `../web/vendor/`, `../web/mediapipe/` | WebGazer archive above; includes @mediapipe/face_mesh 0.4.1633559619 | Extracted bytes match archive; includes source map and original zero-byte `.data` |
| `../models/mediapipe/face_landmarker.task` | https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task | SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| `../models/gazefollower/base.mnn` | gazefollower 1.0.2 Python distribution, `gazefollower/res/model_weights/base.mnn` | SHA-256 `2f96b95275fe6d7b79e98df3237ebb96e15ef5522c96968f08167da7e1954a96`; matches distribution RECORD |
| `sources/eyetrax_gaze_0.4.0.py` | EyeTrax 0.4.0 Python distribution, `eyetrax/gaze.py` | Unmodified source, verified against distribution RECORD; used only for constructor parity tests; MIT notice in `licenses/EyeTrax-MIT.txt` |

Copyright/license notices are retained in the npm archive and
`web/vendor/WebGazer-LICENSE.md`. Full license texts and Python distribution
notices are copied into `licenses/`. GazeFollower carries CC BY-NC-SA terms.
WebGazer carries GPL-3.0-or-later terms; MediaPipe carries Apache-2.0 notices.
Refer to the original files for complete terms; this bundle grants no additional
commercial-use rights. Python packages and their native libraries must still be
installed with the pinned `requirements.txt`; interpreter/site-packages are not
copied between operating systems.
