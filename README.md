# Makeup Refine — technique-planned prototype

The current product flow is **Selfie → Optional Style (Auto) → Select techniques → Generate → Before/After Slider → How to Achieve This Look**. A vision call measures the original selfie and proposes techniques from the [mapping table](docs/technique-mapping-table.md). Face landmarks supply missing spatial measurements when the corresponding region is confidently visible; local rules may then add matching placement candidates, but never invent color deltas. Planning aims for **5 distinct makeup areas** by adding catalogued style-polish techniques when measured triggers cover fewer areas, so the final image has a better chance of showing **at least 5 visible changes**. Baseline placement refinements cover brows, eyeliner, eyeshadow, lips and blush when those regions are visible; this is a visibility-based styling option, not a claim that the face has a defect. It keeps **at most 7 techniques**. Occluded or uncertain regions are skipped, so fewer may remain. The image editor receives the original selfie, chosen style, and selected techniques. The final photograph remains the source of truth: a separate vision call compares the original and enhanced images and explains only visible changes. There is no makeup questionnaire, account system, server, or database.

**Status: local Python prototype, not an iOS app.** The technique-planning flow is implemented and covered by mocked-provider tests. Its numeric trigger thresholds are conservative experiment values and have not been calibrated on a diverse portrait set. Earlier trials showed that fading the API image back toward the original made planned changes hard to see. The current flow preserves the API makeup strength, repairs small coherent camera movement, and retries once from the original if checks still fail; the selected list is intent, not proof of execution. The original masked-edit experiment is preserved as `makeup-refine-legacy`. [Previous image-first flow and limitations](docs/IMAGE_FIRST_FLOW.md) provides historical context.

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

## Run the current technique-planned flow

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

Auto uses the current confidence-first technique ordering and a conservative face-anchored mask. Each named style has a technique preference order, provisional measurement thresholds and a placement-intensity scale. Original-photo measurements, visibility, confidence and lighting gates still decide whether a technique can be selected; the applied profile and evidence are recorded in the output. For example, Korean Soft can select a softly graduated lip color when lip contrast is below 0.25, while Auto uses 0.20. Named styles also use a wider cosmetic mask around selected brows, eyes, nose, cheeks and lip regions; eye interiors and the mouth opening stay protected. These initial style values have not been calibrated for appearance quality. The mask guides the image model; the returned image is checked because the provider may not follow the mask precisely.

Facial base makeup is permitted only when the plan selects a foundation technique, and each foundation technique supplies its own small, landmark-anchored area such as an under-eye or cheekbone/bridge highlight. Generation and protected-pixel checks use the selected technique masks; there is no automatic full-face complexion union. The landmark mask approximates facial skin; it cannot identify hair or glasses crossing the face, so the visual comparison must still check their preservation. Global whitening, artificial texture removal and relighting remain outside the brief.

Foundation edits may soften the contrast of under-eye shadows, but they must keep wrinkles, creases, pores and other age cues visible. The pipeline measures fine texture inside a selected foundation mask and restores only the original high-frequency detail if the image editor smooths it below the preservation floor; the generated tone and coverage remain in place.

Auto and named styles keep the facial base region closed unless the plan explicitly selects a foundation technique. A named style can widen the selected eye, brow, nose or lip placement masks, but it does not grant permission to repaint the entire face. This prevents a cosmetic edit from introducing geometric deformation through an unnecessarily large mask.

The comparison creates a complexion step only when the actual pair shows a confident, reproducible base-makeup change. It never appends generic foundation advice to justify all differences. Observed supplemental complexion changes are recorded separately from the selected techniques; they do not inflate the count of successfully demonstrated planned regions. The existing seven-technique planning limit remains unchanged.

The accepted `enhancedImage.png` is the API photograph at the original working size. The app does not fade cosmetic changes or locally rebuild lips in this path. It may apply one uniform translation/rotation/scale transform to correct small whole-frame movement, with no local face warping. The transform must improve protected-image pixel agreement, must keep shape residuals within the existing limit, and may restore at most 2% uncovered frame-border pixels from the original (never makeup). Geometry is detected again afterward. A failed numeric check triggers at most one corrective retry using the same original photo and technique plan. These heuristic checks still need validation on a diverse portrait set.

The protected-pixel gate now uses provisional limits of mean RGB delta ≤6 and at most 25% of protected pixels above an 8-level delta. These limits account for modest provider tone/texture variation around a permitted base-makeup edit. They do not approve a result by themselves: facial landmark checks and the original-versus-enhanced preservation comparison still reject scene or identity changes.

Eye makeup is constrained separately: eyeliner stays on upper-lid skin just outside the lash roots with a small visible skin gap, and eyeshadow blends upward and outward. Neither may enter the eye opening or cover the visible iris/eye white. The generated mask also protects the aperture plus a small buffer; the prompt does not require a particular lash-line thickness.

When selected techniques share a visual neighborhood, their masks are merged into a bounded group with a short transition margin. The margin lets one image-generation pass blend adjacent pigment and finish changes without opening an unselected feature or turning the full face into an editable canvas.

The image-edit request now states these geometry constraints before generation: preserve inter-eye, eye-to-nose and nose-to-mouth distances, nose and mouth widths, facial symmetry, eye opening and the face outline. The post-generation checks remain as verification because a prompt cannot technically guarantee that an image model will follow every constraint.

The acceptance check also compares eye-opening, nose-width and mouth-width ratios between the original and generated image. A global shift or scale can pass landmark alignment while still changing these local proportions, so a relative change above 5% triggers the bounded correction retry. Eye-opening is directional: either eye may stay the same or become slightly more open for selected eyelid makeup, but any decrease is rejected regardless of how small it is.

The older local compositing experiment remains available for diagnosis on a saved candidate, without an API call:

```bash
PYTHONPATH=src .venv/bin/python -m makeup_refine.recompose_cli outputs/previous-run \
  --output outputs/repaired-run --landmark-model models/face_landmarker.task
```

This creates a fresh image pair and slider. Previous instructions are intentionally cleared because they have not been compared against the repaired image.

The private output directory contains `originalImage.png`, `enhancedImage.png`, `result.json`, and `review.html`. The enhanced photograph is a single full image. The report compares the two separate images with a draggable divider and an accessible range slider. Instructions come from observed differences in eyebrows, eyeliner, lashes, eyeshadow, nose contour, blush, lips, or complexion; unchanged and low-confidence areas are omitted. No template advice is substituted when comparison fails.

Generation first makes one vision request to measure and choose techniques, then one image-edit request, then one comparison request. If no technique qualifies, the original is retained as `enhancedImage.png` and the latter two calls are skipped. An identical pixel result skips comparison. There is at most one automatic paid image retry after a failed geometric or protected-pixel check; set `--max-edit-attempts 1` to disable it. Candidates, aligned candidates, and attempt diagnostics are saved separately. Transport errors are not automatically retried. If instructions fail, the image remains saved. Retry **only the comparison**:

```sh
makeup-refine --retry-instructions outputs/look-001 --vision-model YOUR_VISION_MODEL
```

The current path preserves color conversion, metadata stripping, local face/quality checks, and the dimension/landmark guard. It sends the original working photo and a same-size face-anchored cosmetic mask. The API result is evaluated after bounded spatial registration; local code does not make its makeup lighter. Registration and changes to unselected pixels are recorded separately. A separate original-versus-result comparison creates the user steps only after the image passes numeric checks. Human review remains necessary because landmark and pixel-difference checks cannot prove identity preservation or good makeup taste.

For GPT Image 2, input and output use the same valid canvas. For the 856 × 1200 test photo this adds four protected edge pixels on each side, without resizing the photo content; the returned border is cropped away exactly. Inputs below the minimum pixel area are uniformly enlarged before this small padding step, and only those outputs require resizing back. Oversized sources are reduced to supported limits. The app no longer arbitrarily reduces all photos to a 1024-pixel edge.

In a live direct-output test on `IMG_1202.JPG`, the 856 × 1200 source reached the image API without the old 1024-pixel downscale. The returned candidate changed makeup visibly, but shifted facial landmarks by 0.0164 of the image dimensions (limit 0.0120) and changed unselected pixels substantially (mean 13.84; 44.3% above an 8-level RGB delta). The direct result was correctly rejected and kept only as `outputs/img1202-direct-api-016/candidateImage.png` for diagnosis; no `enhancedImage.png` or instructions were accepted. This shows why a prompt and provider mask alone cannot guarantee a usable final result. The app now reports the failure instead of quietly fading it back toward the original.

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

The recovery test of the saved 016 candidate reduced maximum landmark error from 0.01641 to 0.00442 using a single similarity transform, retaining full makeup strength. The preview is `outputs/alignment-diagnostic-017/review.html`. Two new edits with the same original and plan (`outputs/img1202-recovery-018`) passed geometry either directly or after registration, but both still exceeded the experimental protected-pixel thresholds. This demonstrates recovery of camera drift on this sample, not proof of general identity preservation or an accepted end-to-end result. The remaining pixel differences must not be confused with geometry failure.

Rechecking the saved, aligned 018 image with facial base makeup permitted reduced protected mean pixel delta from 5.78 to 5.44 and the fraction above 8 from 22.3% to 19.1%. It now falls within the provisional pixel gate; no new image or comparison API call was made and the saved candidate was not altered. The diagnostic is `outputs/img1202-recovery-018/complexion-policy-review.json`. This is only a numerical precheck, not proof of unchanged background or identity.
