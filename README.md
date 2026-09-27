# Makeup Refine — image-first prototype

The current product flow is **Selfie → Optional Style (Auto) → Generate → Before/After Slider → How to Achieve This Look**. The image editor receives the original selfie and style directly. Only after the final photograph exists does a separate vision call compare the original and enhanced images and explain the observed makeup changes. No makeup questionnaire, intermediate advice plan, account system, server, or database is involved.

**Status: local Python prototype, not an iOS app.** The revised flow is implemented and covered by mocked-provider tests. Prior Auto trials exposed lip-step omission and facial drift. Explicit assessments fixed the omission on an earlier saved pair; face-anchored compositing and measured lip-boundary blending now address later drift and edge artifacts. A complete Korean Soft run generated an image and steps, but manual review found visible eye-region seams and overconfident text claims. Its saved candidate has since been recomposited locally with full-face tone matching and automatic lip-edge repair, retaining the fuller generated lip shape. The repaired image has no fresh comparison instructions. The original masked-edit experiment is preserved as `makeup-refine-legacy`. [The revised flow and limitations](docs/IMAGE_FIRST_FLOW.md) supersede conflicting behavior in [the original design](docs/DESIGN.md).

## Install

Verified on this Apple Silicon laptop with Python 3.9.6 and MediaPipe 0.10.35. The existing `.venv` is ready to use; Python does not need to be replaced. For a fresh environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[landmarks,dev]'
mkdir -p models
curl -L https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task -o models/face_landmarker.task
```

The landmark asset comes from Google's [Face Landmarker documentation](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python). It runs locally and is not checked into Git.

## Check a photo locally — no API key

From the project directory:

```sh
source .venv/bin/activate
makeup-check --doctor
makeup-check /absolute/path/to/selfie.jpeg --output outputs/check-001
```

`--doctor` loads the actual model and verifies that a blank synthetic image produces no faces. The photo command checks the input and writes `original.png`, three feature masks, `preflight.json`, and an offline `review.html`. Open the HTML file in a browser to inspect colored overlays. These are candidate masks, not makeup recommendations or an AI-refined photo. No provider is instantiated and no photo is uploaded in this mode.

JPEGs containing multiple pictures (MPO, including phone HDR JPEGs) use only the primary photograph. Embedded ICC color profiles are converted to standard sRGB before any processing; outputs retain an sRGB profile. EXIF/GPS and the secondary image are discarded. This is an SDR workflow; it does not reproduce a device's HDR gain-map rendering. HEIC is not yet supported; export a JPEG first.

On macOS, MediaPipe can initialize graphics services even when CPU inference is selected. If running inside a restricted sandbox causes a native graphics error, run this local check from a normal Terminal. In a restricted environment, set `MPLCONFIGDIR` to a writable cache directory if Matplotlib reports a cache-permission warning.

## Run the current image-first flow

Copy `.env.example` to `.env` in the project root, beside `pyproject.toml`, and set `OPENAI_API_KEY`. Existing environment values take precedence. The file is ignored by Git. Reinstall the editable package after updating to register both commands:

```sh
source .venv/bin/activate
pip install -e '.[landmarks,dev]'
makeup-refine /absolute/path/to/selfie.jpeg \
  --output outputs/look-001 \
  --landmark-model models/face_landmarker.task \
  --vision-model YOUR_VISION_MODEL \
  --edit-model YOUR_IMAGE_EDIT_MODEL
```

Omit `--style` for **Auto**, or select `Natural`, `Work / Polished`, `Korean Soft`, `Fresh`, `Date Night`, `Sophisticated`, or `Soft Glam`; quote names containing spaces, e.g. `--style "Soft Glam"`. All options use the same pipeline and build on existing makeup where appropriate. Model names stay explicit; use models enabled for your API account.

Auto uses the conservative face-anchored mask. Any explicitly selected style uses a wider cosmetic mask around the brows, eyes, nose, cheeks and lip outline; eye interiors and the mouth opening remain protected. Selected styles also transfer a bounded, low-frequency complexion tone across facial skin to reduce visible oval seams while retaining original skin texture. Fixed circular cutouts below the nostrils were removed because they caused dark spots against that complexion layer. The initial width multiplier is 1.25 and complexion strength is 0.6; neither has been calibrated for appearance quality. The result records `maskCoverageFraction`, `faceBaseCoverageFraction`, and `faceBaseStrength` so coverage can be inspected.

Generated lip fullness and texture are retained. Local code detects both lip contours, checks the mouth opening, and tries three surrounding-skin margins. A Poisson blend matches the surrounding skin while preserving the generated lip gradients. Boundary jumps, broad and small skin patches, lip-detail loss, and final facial movement are checked automatically. The best passing result is kept; failure rejects the image instead of reverting to the original lip shape. Diagnostics are saved under `lipBlendQuality`. These heuristic thresholds still need validation on a diverse portrait set.

To repeat local compositing and its checks on a saved candidate without any API call or manual coordinates:

```bash
PYTHONPATH=src .venv/bin/python -m makeup_refine.recompose_cli outputs/previous-run \
  --output outputs/repaired-run --landmark-model models/face_landmarker.task
```

This creates a fresh image pair and slider. Previous instructions are intentionally cleared because they have not been compared against the repaired image.

The private output directory contains `originalImage.png`, `enhancedImage.png`, `result.json`, and `review.html`. The enhanced photograph is a single full image. The report compares the two separate images with a draggable divider and an accessible range slider. Instructions come from observed differences in eyebrows, eyeliner, lashes, eyeshadow, nose contour, blush, lips, or complexion; unchanged and low-confidence areas are omitted. No template advice is substituted when comparison fails.

Generation makes one image-edit request, followed by one comparison request. An identical pixel result skips comparison. There are no automatic paid retries. If instructions fail, the image remains saved. Retry **only the comparison**:

```sh
makeup-refine --retry-instructions outputs/look-001 --vision-model YOUR_VISION_MODEL
```

The new path preserves color conversion, metadata stripping, local face/quality checks, and the dimension/landmark guard. It sends a face-anchored cosmetic mask with the original photo, including brow/eye placement, nose bridge and nostril-side contour, blush, and a lip-outline allowance. It aligns coherent whole-face recomposition and composites permitted makeup regions. The fuller lip contour is blended through a locally computed region; the original mouth opening is protected. Excessive mouth changes fail validation. Eye-region strength is controlled locally. Pixels outside the union of the cosmetic mask, adaptive lip region and optional complexion mask remain equal to the original. Non-affine face changes or excessive final landmark movement still fail; post-generation visual comparison and human review remain necessary. A detected non-makeup change marks the result rejected and suppresses its steps and comparison preview.

For GPT Image 2, small inputs are proportionally enlarged to a valid canvas instead of being surrounded by artificial pixels. This avoids the padding-associated zoom observed on the 788 × 524 test photo. The old rejected candidate can be aligned and composited offline, but that recovery does not prove how a fresh masked API request will behave.

## Run the legacy masked experiment

The spike now separates generation strength from final presentation. See
[the controlled-blending experiment](docs/BLENDING_SPIKE.md) for the full-strength
candidate workflow and the offline 0.3/0.5/0.7 calibration tool.

Copy `docs/provider-review.example.json` to a local review file. Record the evaluated model, review date and evidence for permitted face editing and mask support. The example intentionally does not claim either gate is cleared. The OpenAI adapter follows the [image editing API](https://developers.openai.com/api/docs/guides/image-generation); API support alone is not proof of policy clearance or acceptable results. Choose vision and image models available to your account explicitly.

Put your OpenAI API key in `.env` in the project root:

```dotenv
OPENAI_API_KEY=your_actual_key
```

Put `.env` in the project root, beside `pyproject.toml`.
The file is ignored by Git. The command reads it automatically when run from the
project directory; an existing `OPENAI_API_KEY` environment variable takes precedence.
For a fresh checkout, copy `.env.example` to `.env` and replace the placeholder.
Then run:

```sh
makeup-refine-legacy private-fixtures/selfie.jpg \
  --output outputs/trial-001 \
  --landmark-model models/face_landmarker.task \
  --vision-model YOUR_VISION_MODEL \
  --edit-model YOUR_IMAGE_EDIT_MODEL \
  --blend-strength 0.5 \
  --provider-review private-fixtures/provider-review.json
```

Outputs are `original.png` (orientation-normalized, metadata-stripped working image), `refined.png`, `mask.png`, `result.json`, and `review.html`. The offline report includes a keyboard-accessible before/after slider and instructions. A no-changes outcome writes only the original and JSON. Failures after pipeline initialization write structured error JSON and exit nonzero. Output directories must be new to prevent stale results from mixing with another photo.

Photos are downscaled to a maximum 1024-pixel edge before paid calls. The complete frame is sent; cropping is disabled. The refined PNG matches this working original's dimensions, not necessarily the camera file's resolution. Provider output with different dimensions is rejected; no warping or silent resizing is used. Some image models have fixed output sizes, so arbitrary-aspect photos may fail this gate. Establish compatible model/dimension behavior during the spike before promoting an adapter.

## Legacy masked experiment: guarantees and limits

- Cheap resolution, exposure, blur and face-count/size checks run before AI calls. Face-crop checks prevent a bright background hiding an underexposed face.
- Pydantic rejects unknown fields, unsupported refinements, more than three changes, duplicate areas, and changes to uncertain makeup. Free-text instructions still require semantic review.
- MediaPipe contours produce upper-lash, upper-eyelid and lip masks that follow head roll. Eye interiors and the inner mouth are explicitly cut out. These geometric masks need validation across pose, skin tones, eye anatomy, glasses and makeup styles. Detected landmarks do **not** establish that occluded eyes/lips are visible; robust visibility gating remains unvalidated.
- One edit request covers the union of areas and requests a clearly visible full technique. Final strength is controlled deterministically by `--blend-strength` (experimental default 0.5). A second generation attempt can follow a candidate/geometry failure; a too-weak or too-strong final blend returns an error for local tuning instead of paying for another image. There are no hidden HTTP retries.
- Compositing copies pixels outside mask support exactly and feathers only inside that support. The provider receives fully transparent editable pixels; local feathering is kept separate and multiplied by blend strength exactly once. Candidate geometry is checked before blending, so opacity cannot conceal shifted landmarks. Tests enforce these guards, correct provider alpha-mask polarity, bounded retries and no paid calls on rejected inputs.
- Automated gates check dimensions, protected-landmark motion and per-region pixel-delta bounds. They are heuristic guards, **not proof of identity, realism, subtlety or a useful makeup improvement**. Every successful report explicitly requires human review and keeps `phase1Validated: false`. Natural eyelid shadows and pigmentation must not be treated as evidence of makeup without a confident assessment.
- Results include short English/Chinese makeup instructions. Click a step in the offline report to highlight its location; eye masks get separate outlines when separated. JSON retains the detailed instruction alongside the short guide. These mask outlines are location hints, not precise technique arrows or proof that the intended change was achieved.
- No credentials, images or raw provider errors are logged. Source photos and normalized photos are not sent to analytics.

This local experiment keeps outputs until **you delete them**. They are stored in a directory created with owner-only permissions and excluded from Git under `outputs/`. It does not implement the future service's automatic 15–30 minute object-storage retention. Provider-side retention is separate and must be checked in the review.

## Verification

```sh
pip install -e '.[dev]'
pytest -q
```

Tests use synthetic image data and fake providers, plus mocked HTTP contracts. They do not demonstrate real makeup editing quality. For Phase 1, use a small consented internal test set with varied skin tones, lighting, angles, makeup and no-change examples. Inspect `original.png`, `refined.png`, and `mask.png` side by side at 100%; record results in [the evaluation checklist](docs/EVALUATION.md). Do not advance to backend/mobile on unit tests alone.
