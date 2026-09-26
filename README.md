# Makeup Refine — local technical spike

Implementation of Phase 1 of [the supplied design](docs/DESIGN.md). Takes one local selfie, validates it, runs combined makeup analysis/planning, derives feature masks with MediaPipe Face Landmarker, calls a masked image editor, composites the result, and writes a photo plus structured JSON. Provider interfaces allow replacing analysis, editing, and landmark detection independently.

**Status: experimental implementation, not a validated MVP.** No backend or mobile app is built yet. Real-image subtlety, identity, landmark reliability, provider policy, and mask-edit quality must pass the design's Phase 1 review before proceeding. The first user-authorized trial passed numerical checks but was rejected visually: the loader had discarded a Display P3 profile, changing the apparent tone, and the eyeshadow adjustment was not useful. Color management is now corrected and regression-tested; human acceptance and broader test-set evaluation remain pending.

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

## Run a consented test photo

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
makeup-refine private-fixtures/selfie.jpg \
  --output outputs/trial-001 \
  --landmark-model models/face_landmarker.task \
  --vision-model YOUR_VISION_MODEL \
  --edit-model YOUR_IMAGE_EDIT_MODEL \
  --blend-strength 0.5 \
  --provider-review private-fixtures/provider-review.json
```

Outputs are `original.png` (orientation-normalized, metadata-stripped working image), `refined.png`, `mask.png`, `result.json`, and `review.html`. The offline report includes a keyboard-accessible before/after slider and instructions. A no-changes outcome writes only the original and JSON. Failures after pipeline initialization write structured error JSON and exit nonzero. Output directories must be new to prevent stale results from mixing with another photo.

Photos are downscaled to a maximum 1024-pixel edge before paid calls. The complete frame is sent; cropping is disabled. The refined PNG matches this working original's dimensions, not necessarily the camera file's resolution. Provider output with different dimensions is rejected; no warping or silent resizing is used. Some image models have fixed output sizes, so arbitrary-aspect photos may fail this gate. Establish compatible model/dimension behavior during the spike before promoting an adapter.

## Guarantees and limits

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
