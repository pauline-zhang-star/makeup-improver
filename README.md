# Makeup Refine — technique-planned prototype

The current product flow is **Selfie → Optional Style (Auto) → Model designs a coordinated look → Validate catalog actions → Generate → Before/After Slider → How to Achieve This Look**. The planning model chooses at most seven techniques from the [catalog](docs/technique-mapping-table.md), based on the original photo, existing makeup and requested style. Each proposal includes a concrete visual observation, a style/cohesion reason, a photo-specific application and bounded rendering strength. It can preserve already-suitable areas or return fewer changes. Code does not add techniques to fill a four-area quota, apply a fixed style recipe, or use uncalibrated aesthetic scores to decide which techniques qualify. The final photograph remains the source of truth: a separate comparison call explains only observed changes. There is no makeup questionnaire or account system; public deployment uses a small database only for anonymous quotas and metadata-only access events.

**Status: Python prototype with a localhost Web page and a public deployment configuration, not an iOS app.** [Current planning architecture](docs/MODEL_PLANNING_FLOW.md) describes the model/code boundary and remaining limitations. Provider integration is covered by mocked tests; the revised planning flow still needs a real-photo visual trial. Region visibility, allowed techniques, conflicts, strength limits and color-reference reliability are checked locally; face landmarks still anchor masks and geometry checks. The current flow preserves the API makeup strength, repairs small coherent camera movement, and retries once from the original if checks fail. A selected technique remains intent, not proof of execution or good taste. Historical threshold/recipe selection is retained only for offline audits. The original masked-edit experiment remains available as `makeup-refine-legacy`.

## Install

Verified on this Apple Silicon laptop with Python 3.10 and MediaPipe 0.10.35. The local `.venv-mp021` contains the required HEIC decoder; the unqualified `python` command currently points to a separate Conda environment without `pillow-heif`. For a fresh environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[landmarks,dev]'
mkdir -p models
curl -L https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task -o models/face_landmarker.task
```

The landmark asset comes from Google's [Face Landmarker documentation](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python). It runs locally and is not checked into Git.

## Open the Web page

From this project directory, with `.env` containing `OPENAI_API_KEY` and the landmark model installed as above:

```sh
MPLCONFIGDIR=/tmp/mpl PYTHONPATH=src .venv-mp021/bin/python -m makeup_refine.web_app
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Use the 中文 / EN toggle at the top to switch the page and result guidance without regenerating an image; the choice is saved in the browser. Choose a JPG, PNG, or HEIC photo, optionally choose a style, then generate. The page shows a click-to-jump and draggable original/result comparison, numbered arrows and observed instructions for accepted results. New planning and comparison calls save English and Simplified Chinese instructions in the same API responses. Older runs that lack Chinese instructions show the original English text with a clear notice. Rejected candidate images remain available for diagnostic comparison and their planned techniques are clearly labeled as unconfirmed. Expand Run details / 本次记录 for selected techniques, checks and estimated API cost; the full test record opens the existing raw audit with actual API prompts and responses. Photos, logs and results stay under ignored `outputs/web-uploads/` and `outputs/web-runs/`. The server listens only on this computer's loopback address, stores no account data, and does not put the API key in browser code. Clicking Generate sends the photo to the configured OpenAI API for planning, image generation and comparison and may incur API charges. Stop the page with Ctrl-C in its Terminal.
If you activate a newly created `.venv`, install the project dependencies with `pip install -e '.[landmarks,dev]'` before running the same command with `.venv/bin/python`. The `pillow-heif` package is required for HEIC support even when testing a JPEG.

## Free Vercel deployment

Vercel's [Docker Functions](https://vercel.com/docs/functions/container-images) can run this Python/MediaPipe service on the free Hobby plan. [Dockerfile.vercel](Dockerfile.vercel) starts the single-request adapter; each request runs the existing CLI pipeline and removes its temporary files before returning. The original photo stays in the browser for the slider, and only a compressed enhanced image and the guidance return from the server. Refreshing the page loses that result. Neither Vercel nor Upstash is configured by this repository to persist photos, results, provider traces or prompts. The app does send the working photo to the configured OpenAI API for generation.

To deploy, import [this GitHub repository](https://github.com/pauline-zhang-star/makeup-improver) into a **Vercel Hobby** project. Vercel detects `Dockerfile.vercel` at the repository root. Keep Fluid Compute enabled so a request can run for up to the [Hobby five-minute maximum](https://vercel.com/docs/functions/limitations). No paid Vercel plan or persistent image storage is required. The first real image run still needs verification on Vercel; a slow provider response can exceed the five-minute limit. The free service accepts a compressed upload smaller than 2.5 MB and returns a JPEG result under 2.2 MB to stay within Vercel's 4.5 MB request/response cap. The browser compresses only when necessary and uses the sent working photo as the before image.

Create a **free Upstash Redis** database in the [Upstash Console](https://console.upstash.com/), open its **REST** connection tab, and copy `UPSTASH_REDIS_REST_URL` and the **Standard** `UPSTASH_REDIS_REST_TOKEN`. The [Upstash free tier](https://upstash.com/pricing/redis) has a hard command allowance; do not upgrade it to a paid plan. In the Vercel project's **Settings → Environment Variables**, set those two secrets plus `OPENAI_API_KEY` (from the [OpenAI API dashboard](https://platform.openai.com/api-keys)), `MAKEUP_VISITOR_SECRET` (a new random secret, e.g. `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`), `MAKEUP_VISITOR_DAILY_LIMIT=2`, and `MAKEUP_GLOBAL_DAILY_LIMIT=50`. Add them to Production before the first deployment, then redeploy when adding or changing a value. Never commit these values. If the Upstash secret is missing or Redis is unavailable, generation fails closed before any OpenAI call.

The anonymous ID is a signed, secure, HttpOnly browser cookie. Redis atomically reserves two starts per browser and 50 site-wide per UTC day; it refunds a reservation when the local photo checks stop the workflow before any provider API request. It keeps only hashed visitor IDs, counters and up to 1,000 metadata-only events per UTC day under `makeup:events:YYYY-MM-DD` for about 30 days; there is no photo in Redis. The result exists only in the active browser page after the temporary server request ends. Clearing cookies can reset an individual's ID but cannot bypass the site-wide limit. OpenAI API calls still incur their normal charges even when hosting remains free.

The Vercel request ends after 270 seconds. The page shows elapsed time but cannot show a live stage because this adapter sends one synchronous response. On timeout, the server reports the last recorded API stage and whether a provider call began; a try is refunded only when none began. If an enhanced image already passed local checks and only the final comparison timed out, the page receives that image for before/after viewing without unverified how-to steps. Temporary server files are deleted after the response, so an older timed-out run cannot be recovered.

## Paid Render alternative

The supplied [Dockerfile](Dockerfile) and [render.yaml](render.yaml) prepare one Render web service with a 2 GB RAM compute plan and a 1 GB persistent disk **for quota counters and metadata-only access events**. This is a paid hosting configuration; confirm the current price in Render before applying it. It is separate from the duihuiqu Vercel app because makeup generation runs a long Python/MediaPipe process and needs temporary result files. The service exposes `/health` and binds to Render's `PORT` on `0.0.0.0`.

Connect this repository to Render as a Blueprint. During initial setup, put the OpenAI key in the `OPENAI_API_KEY` secret field in Render; create a key in the [OpenAI API dashboard](https://platform.openai.com/api-keys) if needed. Do not copy the local `.env` to Render or commit it. Render generates `MAKEUP_VISITOR_SECRET`; the Blueprint sets `MAKEUP_PUBLIC_MODE=1`, an ephemeral photo directory at `/tmp/makeup-refine`, and a separate metadata database at `/var/data/access.sqlite3`. A missing key, secret, or metadata path prevents public startup. Set a provider-side spend limit in the OpenAI dashboard before sharing the URL.

Public-mode limits are two provider-started generations per signed anonymous browser cookie and 50 across the entire site per UTC day. A malformed upload, unavailable worker, or photo rejected before any API request does not consume a try. Clearing cookies can create a new anonymous ID, but it cannot bypass the global limit. Only one image job runs at a time; a busy request receives a retry message without using a try. The page shows the remaining counts. These limits are enforced in SQLite with an atomic reservation before any API workflow starts, and remain in force across service restarts because only the metadata database is on the persistent disk.

Public-mode uploads, results and workflow logs are temporary files, removed after two hours by a background cleanup task; they are **never mounted on the persistent disk**. A saved result link expires when those files are removed, and an in-progress job is not deleted. The metadata-only access log keeps page views, accepted/blocked starts, invalid uploads and review views for 30 days; it stores a keyed hash of the visitor ID, event time and optional job ID, not raw selfies, raw IP addresses, prompts or API keys. On the service shell, `python -m makeup_refine.public_guard --db /var/data/access.sqlite3 --last 30` prints daily event totals and recent events. Local mode remains on loopback with no daily quota and retains its existing `outputs/web-*` test artifacts.

Before any paid call, the current flow removes paired, full-width black screenshot bars when their edges are unambiguous. It also makes a conservative face-centered crop only when the detected face is small in the frame, with generous space for hair and shoulders. Ordinary close portraits are unchanged. Cropping does not rescale or retouch pixels. The raw Web upload remains in the mode's upload directory (`outputs/web-uploads/` locally; `/tmp/makeup-refine/web-uploads/` in public mode); a cropped run additionally saves `uploadedImage.png` and records `inputCrop` (source size, crop box, working size and reason) in the report. `originalImage.png`, the API input and the before/after slider all use the same cropped working frame. This can reduce unwanted model reframing but cannot guarantee it; generation still goes through the existing geometry and preservation checks.

## Check a photo locally — no API key

From the project directory:

```sh
source .venv/bin/activate
makeup-check --doctor
makeup-check /absolute/path/to/selfie.jpeg --output outputs/check-001
```

`--doctor` loads the actual model and verifies that a blank synthetic image produces no faces. The photo command checks the input and writes `original.png`, three feature masks, `preflight.json`, and an offline `review.html`. Open the HTML file in a browser to inspect colored overlays. These are candidate masks, not makeup recommendations or an AI-refined photo. No provider is instantiated and no photo is uploaded in this mode.

JPEGs containing multiple pictures (MPO, including phone HDR JPEGs) and HEIC photos use only the primary photograph. Embedded ICC color profiles are converted to standard sRGB before any processing; outputs retain an sRGB profile. EXIF/GPS and secondary images are discarded. This is an SDR workflow; it does not reproduce a device's HDR gain-map rendering. The web app accepts HEIC/HEIF; browsers that cannot decode a HEIC locally can send files up to 3 MB to the Vercel server for decoding, while larger HEIC files need a browser with native HEIC decoding or a JPEG export.

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

Style includes finished makeup intensity. Auto targets light, airy everyday makeup and can reduce heavy existing brow or lip pigment; Date Night targets richer, coordinated evening definition. Natural, Korean Soft and Fresh are not automatically stronger just because they are named styles. Named styles supply qualitative art direction; the model adapts technique choice to the actual photo, without fixed per-style technique lists or default lip deltas. Model order, observations and application details are preserved. Local validation can reject a proposal but cannot replace it with an invented fallback. It also checks color direction for brow darkening (negative lightness), brow softening (positive lightness), and lip desaturation (negative chroma), preventing a reduction technique from carrying opposite-signed parameters. The report records accepted proposals, rejection reasons, preserved areas and the overall look direction. Named styles retain the existing wider cosmetic masks; eye interiors and the mouth opening stay protected. Placement intensity and relative OKLCH deltas are rendering controls with existing caps, not beauty scores. Those caps and visibility confidence remain experimental; passing them does not prove identity preservation or aesthetic quality.

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


### API usage and estimated cost

Each CLI run now writes `api-usage.json` and embeds its accounting summary in `result.json` and the slider review page. Planning, image generation (including retries and locally rejected candidates), and comparison are itemized. Records include timestamps, requested model, request ID when available, API-reported token counters, and a dated USD price snapshot. Amounts are estimates at standard rates, excluding tax, not provider invoices. The centralized table in `src/makeup_refine/api_usage.py` must be updated when public prices change.

The ledger is atomically saved before a request and immediately after its response, before content parsing or quality validation. Interrupted requests, missing usage, incomplete image token breakdowns, and unrecognized model prices remain unknown; the known subtotal is shown separately from the full total. No photo, prompt, API key, or full response is written to the usage ledger. Explanation-only retries append to the existing ledger without repricing or counting earlier calls again. Older results with no usage history are explicitly incomplete; their costs are not reconstructed from guesses. Opening the saved HTML never calls an API.

Rates checked against [OpenAI pricing](https://developers.openai.com/api/docs/pricing) on 2026-09-30: GPT-4.1 mini input/cached input/output $0.40/$0.10/$1.60 per million tokens; GPT Image 2 text input/image input/image output $2.50/$4.00/$15.00. Direct image edits do not receive a cached-input discount. Tests use mocked responses and incur no API charges.

### Complete trial review

Every new CLI test saves a self-contained `review.html` with technique choices, original observations, style reasons, applications, validated strengths, preserved areas and rejected proposals. New model plans retain `validation_results`; validation stops at the first failure for each proposal. Successful validation means applicable code checks passed, not that the model's aesthetic claims are proven.

`api-trace/index.json` indexes each real request by the same call ID as the usage ledger. Each call folder saves `request.json`, `response.json`, the verbatim `response-body.json`, and exact input/output PNG bytes identified by SHA-256. Request headers and API keys are excluded. These are private photo artifacts and should be deleted with the trial. The report displays actual prompts, parameters, inputs/masks/crops and responses, with collapsible details. Historical requests are labelled unrecorded, never reconstructed from current prompts.

Generation attempts record checkpoints as `passed`, `failed` or `not_run`, including failure messages and available measurements. Both numerically rejected candidates and images rejected by the visual preservation review remain in click-to-jump / drag comparisons. Every saved attempt has its own independently controlled original-versus-candidate slider; raw and aligned/composited views are separate. Provider images with wrong dimensions are retained from the raw trace even when the adapter cannot return an accepted image. If no decodable image was returned, only the error can be shown. Candidate sliders do not bypass acceptance gates or create makeup instructions for rejected results.
