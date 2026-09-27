# AI Makeup Refine — MVP Design Doc

> Implementation revision: [IMAGE_FIRST_FLOW.md](IMAGE_FIRST_FLOW.md) describes
> the current user-approved flow and supersedes the analysis-first, three-area-only
> behavior below. This original design remains as historical context for the legacy experiment.

## 1. Purpose

Build an iOS-first mobile app that lets a user upload or take a selfie with their current makeup.

The system:

1. analyzes the current makeup,
2. generates one subtly refined version of the same photo,
3. lets the user compare the original and refined image using a draggable before/after slider,
4. if the user likes the result, shows exactly what was changed and how to reproduce those changes in real life.

The product should not generate a completely different makeup look.

Core experience:

```text
Upload selfie
→ AI generates subtle refinement
→ Drag slider to compare original vs refined
→ User likes result
→ Show exact makeup adjustments
```

---

## 2. Product Principle

The app should answer:

> "Can my current makeup be improved with a few small, realistic changes?"

The AI should not redesign the user's face or create a dramatically different makeup style.

The user does not need to specify whether they have completed a full face, only eye makeup, or only part of their makeup. There is one entry point: upload a selfie. The AI decides whether useful refinements exist in eyeliner, eyeshadow, lips, or other supported areas.

If the current lip color is not well coordinated with the rest of the makeup, the AI may make a subtle lip-color adjustment in the preview.

---

## 3. Platform Strategy

### MVP

Ship only on iOS.

### Architecture requirement

The codebase should remain Android-ready.

Use:

- React Native
- Expo
- TypeScript

Do not use SwiftUI for the main application.

Native iOS modules may be added only when React Native / Expo cannot support a required feature.

Android is not implemented in MVP, but shared code must avoid unnecessary iOS-specific assumptions.

---

## 4. MVP Scope

### Included

- Take a photo or select a photo from the iOS photo library
- Basic image quality validation
- Upload photo to backend
- Analyze current makeup
- Decide 1–3 subtle refinements
- Generate exactly one refined image
- Show draggable original/refined comparison
- Collect Like / Dislike feedback
- If liked:
  - display changes
  - visually annotate where to adjust
  - explain how to reproduce each change
- Anonymous analytics
- Temporary image storage
- Error handling and one automatic generation retry

### Not Included

Do not implement:

- login
- signup
- database
- user profiles
- subscriptions
- payment
- makeup history
- social feed
- AR makeup
- video
- multiple generated looks
- manual makeup controls
- attractiveness score
- product shopping
- makeup inventory
- brand recommendations
- reference makeup image upload
- Android release

These may be added later.

---

## 5. Allowed Refinements

AI should make only subtle, realistic refinements.

Examples:

- slightly lift eyeliner wing
- slightly shorten or balance eyeliner
- soften eyeshadow edge
- shift eyeshadow slightly upward or outward
- improve eye-makeup balance
- slightly adjust lip color temperature
- slightly adjust lip color brightness/depth
- lightly refine lip shape or edge
- lightly correct left/right asymmetry

### Prohibited MVP behavior

Do not:

- replace the full makeup look
- significantly change eye shape
- change face shape
- enlarge eyes
- shrink nose
- smooth or beautify skin
- change hairstyle
- change lighting
- change expression
- dramatically change lipstick color
- transform one makeup style into a completely different style

The refined image must still clearly be the original user's photo.

---

## 6. Primary User Flow

### Screen 1 — Home

Single primary action:

```text
Upload a selfie
```

Allow:

- Camera
- Photo Library

No other mode selection.

---

### Screen 2 — Processing

Show a simple processing state. The client polls `GET /v1/refinements/{id}` on an interval while showing this screen (see Section 13).

Example:

```text
Analyzing your makeup…
```

Processing pipeline:

1. image validation
2. makeup analysis
3. refinement planning
4. image editing
5. result validation (one automatic retry on failure)

### Failure state (new)

If polling returns `status: "failed"`, or the client-side poll timeout is reached:

```text
Something went wrong generating your result.
[ Try again ]  [ Cancel ]
```

Do not silently return to Screen 1. Show a clear, single retry action. Do not auto-retry the whole pipeline from the client beyond the one server-side retry already performed.

### Cancel during processing (new)

The user may back out while Screen 2 is showing. Stop polling and discard the local job reference; no client-side cleanup call to the backend is required for MVP, since the job is not persisted beyond in-flight processing and images auto-expire per Section 12.

---

### Screen 3 — Result

Display original and refined images aligned exactly.

Use one draggable vertical divider.

Default position:

```text
50%
```

Behavior:

- one side shows original
- the other side shows AI-refined image
- dragging fully one way reveals 100% original
- dragging fully the other way reveals 100% refined
- leaving it near the middle provides a half-face comparison

This is the core result interaction.

Actions:

```text
I like it
Not for me
```

Do not create separate half-face and full-face modes.

### No-changes state (new)

If the result has `status: "completed_no_changes"` (the planner found nothing worth adjusting — this is an allowed, expected outcome, not an error), do not show the slider. Show instead:

```text
Your makeup already looks well-balanced —
we didn't find any subtle changes worth suggesting.
```

with a single action to return to Screen 1. Do not fabricate a refined image or force a comparison when none exists.

---

### Screen 4 — Adjustment Details

Only show after:

```text
I like it
```

Display:

- original photo
- visual annotations
- maximum 5 adjustment instructions

Possible annotation types:

- arrow
- dotted guide line
- translucent highlighted region
- outline

Example:

```text
1. Eyeliner
Lift the outer wing slightly.

2. Eyeshadow
Blend the outer edge slightly higher.

3. Lips
Use a slightly cooler lip tone.
```

The purpose is to show how to reproduce the AI result using real makeup.

---

## 7. High-Level Architecture

```text
React Native / Expo iOS App
          |
          | HTTPS
          v
FastAPI Backend
          |
          +---------------------+
          |                     |
          v                     v
Temporary Image Storage     AI Pipeline
                                |
                                v
                         Makeup Analysis
                                |
                                v
                       Refinement Planner
                                |
                                v
                       Localized Image Edit
                                |
                                v
                         Quality Validation
                                |
                                v
                          Result Response
```

---

## 8. Technology Stack

### Mobile

Use:

- React Native
- Expo
- TypeScript
- Expo Router

Responsibilities:

- camera/photo picker
- image upload
- loading state
- result slider
- annotations
- feedback
- analytics

### Backend

Use:

- Python
- FastAPI
- Pydantic

Responsibilities:

- session creation
- image validation
- orchestration
- AI API calls
- temporary image storage
- result generation
- error handling

Keep AI provider-specific implementation behind interfaces.

Do not directly couple API endpoints to one model vendor.

### Storage

Use temporary object storage.

Examples:

- S3-compatible storage
- Cloudflare R2
- Supabase Storage

Images should expire automatically.

### Analytics

Use an external analytics provider such as:

- PostHog
- Firebase Analytics

No application database is required for MVP analytics.

---

## 9. Backend Project Structure

```text
backend/
  app/
    main.py

    api/
      routes/
        refinement.py
        health.py

    models/
      request.py
      response.py
      refinement.py

    services/
      image_service.py
      makeup_analysis_service.py
      refinement_planner.py
      image_edit_service.py
      quality_service.py
      annotation_service.py

    providers/
      vision_provider.py
      image_edit_provider.py

    storage/
      storage_interface.py
      temporary_storage.py

    repositories/
      result_repository.py
      noop_result_repository.py

    core/
      config.py
      logging.py
      exceptions.py

    tests/
```

---

## 10. Mobile Project Structure

```text
mobile/
  app/
    index.tsx
    processing.tsx
    result.tsx
    details.tsx

  components/
    ImagePicker.tsx
    BeforeAfterSlider.tsx
    MakeupAnnotation.tsx
    PrimaryButton.tsx

  services/
    api.ts
    analytics.ts

  hooks/
    useRefinement.ts

  types/
    refinement.ts

  utils/
    image.ts

  constants/
```

Keep API types centralized.

---

## 11. Future Persistence Design

MVP does not use a database.

However, core services must not assume persistence will never exist.

Define repository interfaces such as:

```python
class ResultRepository:
    async def save_result(self, result):
        ...

    async def get_result(self, result_id):
        ...
```

MVP implementation:

```text
NoOpResultRepository
```

or short-lived in-memory storage.

Future implementation may use PostgreSQL.

Potential future entities:

```text
users
makeup_sessions
refinement_results
feedback
makeup_products
user_makeup_inventory
user_preferences
subscriptions
```

Do not create these tables in MVP.

Future features that may need persistence:

- Sign in with Apple
- paid subscriptions
- generation credits
- saved makeup history
- saved refinements
- My Makeup Bag
- long-term preference learning
- cross-device sync

Images should still live in object storage, not directly in PostgreSQL.

---

## 12. Image Storage

Do not store image binaries in a database.

Use object storage.

MVP requirements:

- original image stored temporarily
- refined image stored temporarily
- signed/private URLs
- automatic expiration/deletion

Since the product is fully stateless (the complete result, including changes, is returned in the poll response — nothing is fetched later), there is no product reason to retain images beyond the active session. Default retention should be short, with a longer value only as a debugging ceiling:

```text
Default: delete within ~15–30 minutes of job completion
(or immediately after the feedback event, if received first)

Configurable ceiling for debugging: up to 24 hours,
should not be the production default
```

Storage interface:

```text
ImageStorage
  upload()
  get_signed_url()
  delete()
```

Future storage providers should be replaceable without changing business logic.

---

## 13. API Design

The full pipeline (validation → analysis → planning → edit → validation, plus a possible retry) can realistically take 10–60+ seconds over a mobile connection. Do not model this as a single blocking request. Use job creation + polling.

### POST /v1/refinements

Create a refinement job. Returns immediately.

Request:

```text
multipart/form-data
```

Fields:

```text
image: file
```

Response (immediate):

```json
{
  "id": "ref_123",
  "status": "processing"
}
```

---

### GET /v1/refinements/{id}

Poll for job status. Mobile client polls this on an interval (e.g. every 1.5–2s) while on Screen 2, with a defined maximum wait (e.g. 90s) after which the client shows a timeout error and the job is abandoned server-side.

Response while processing:

```json
{
  "id": "ref_123",
  "status": "processing"
}
```

Response on success, with changes found:

```json
{
  "id": "ref_123",
  "status": "completed",
  "originalImageUrl": "...",
  "refinedImageUrl": "...",
  "changes": [
    {
      "id": "change_1",
      "area": "eyeliner",
      "type": "lift_outer_wing",
      "instruction": "Lift the outer wing slightly.",
      "annotation": {
        "type": "arrow",
        "points": []
      }
    }
  ]
}
```

Maximum:

```text
3 changes
```

Response on success, with **no worthwhile changes found** (the planner is allowed to return zero — see Section 16):

```json
{
  "id": "ref_123",
  "status": "completed_no_changes",
  "originalImageUrl": "...",
  "refinedImageUrl": null,
  "changes": []
}
```

The mobile client must treat `completed_no_changes` as a distinct, non-error outcome — see Screen 3 below.

Response on failure (validation failed after retry, or generation error):

```json
{
  "id": "ref_123",
  "status": "failed",
  "errorCode": "QUALITY_CHECK_FAILED",
  "message": "We couldn't generate a result this time. Please try again."
}
```

---

### POST /v1/refinements/{id}/feedback

Request:

```json
{
  "liked": true
}
```

No database required.

Send this event to analytics.

---

### GET /health

Response:

```json
{
  "status": "ok"
}
```

---

## 14. Image Quality Check

### Client-side pre-check (new)

Before uploading, run a lightweight on-device check (e.g. basic face detection via the platform's built-in Vision framework, no server round trip) to catch obvious failures — no face, extreme darkness — before spending upload bandwidth or hitting the backend at all. This is a cost-control measure as much as a UX one; the backend check below remains the authoritative gate.

### Backend check

Reject images when:

- no face detected
- multiple dominant faces detected
- face too small
- strong blur
- severe underexposure
- severe overexposure
- eyes or lips not sufficiently visible
- image resolution too low

Return actionable errors.

Example:

```json
{
  "code": "FACE_TOO_SMALL",
  "message": "Move closer and try again."
}
```

Do not send unusable images into expensive AI processing.

---

## 15. Makeup Analysis

Input:

```text
original selfie
```

Output structured data.

Example:

```json
{
  "eyeliner": {
    "detected": true,
    "confidence": 0.93,
    "notes": "Outer wing is slightly horizontal."
  },
  "eyeshadow": {
    "detected": true,
    "confidence": 0.88,
    "notes": "Outer shadow edge could be blended slightly higher."
  },
  "lips": {
    "detected": true,
    "confidence": 0.96,
    "notes": "Current lip tone is slightly warm relative to the eye makeup."
  }
}
```

The model must be allowed to return:

```text
uncertain
```

Never fabricate a confident makeup assessment.

---

## 16. Refinement Planner

Input:

```text
MakeupAnalysis
```

Output:

```text
0–3 RefinementChange objects
```

Suggested schema:

```ts
type RefinementChange = {
  area:
    | "eyeliner"
    | "eyeshadow"
    | "lips";

  type: string;

  severity: "subtle";

  instruction: string;

  rationale?: string;
};
```

All proposed changes must be realistically reproducible without requiring the user to remove and redo the entire makeup.

### Planning preferences

Prefer changes that:

1. require minimal real-world correction
2. are visible enough to compare
3. do not require removing existing makeup
4. improve visual coherence
5. can be explained simply

Avoid:

```text
Replace dark brown eyeshadow with pale pink.
```

when the user would realistically need to remove the existing eye makeup.

Prefer:

```text
Blend the outer edge slightly higher.
```

Lip color may be adjusted more freely because changing lipstick is comparatively easy.

---

## 17. Localized Image Editing

This is the most important technical component, and the least validated. Do not treat it as solved until Phase 1 proves it out.

Do not simply send:

```text
photo + "make the makeup better"
```

and accept a fully regenerated image.

Instead:

```text
original image
+
region mask
+
specific edit instruction
```

Edit only required regions.

### Mask generation (must be named, not assumed)

The region mask is a hard dependency and must be produced by an explicit, named component — not implied. Phase 1 must select and test one of:

- a facial-landmark model (e.g. MediaPipe Face Mesh) to derive eye/lip regions geometrically, or
- a face-parsing/segmentation model that outputs per-feature masks directly.

Example target masks:

```text
eyeliner:
upper lash line + outer eye region

eyeshadow:
upper eyelid + outer blend region

lips:
lip segmentation mask
```

After generation:

```text
final image =
original outside edit mask
+
edited pixels inside edit mask
```

This compositing step is the primary guarantee of both minimal unwanted change and pixel alignment outside the mask (see Section 18). It is not optional and must not be replaced by "trust the model to leave the rest alone."

### Provider policy gate (blocking, must clear in Phase 1)

Many image-generation/editing providers restrict or prohibit photorealistic editing of real human faces for consent/deepfake reasons. Before any backend or mobile work begins, Phase 1 must confirm, for the specific provider(s) under evaluation:

1. the provider's ToS/acceptable-use policy explicitly permits localized editing of real user-submitted face photos for this use case,
2. the provider supports mask-constrained (inpainting-style) editing rather than only full-image regeneration.

If no provider clears both checks, the product is not buildable as specified and the design must be revisited before Phase 2.

### Cost-optimized cropping (gated, non-default — do not ship without passing the test below)

**MVP default: send the full frame to the edit API.** This section describes an optional cost optimization, not a requirement, and it must not be enabled in production until it has passed the equivalence test below. Quality takes priority over cost savings whenever the two conflict.

The optimization: instead of sending the full-resolution photo to the edit API, send a padded crop around the mask's bounding box (roughly 25–40% margin, not a tight crop — the model needs surrounding skin tone/lighting/angle context to blend the edit naturally), then composite the edited crop back into the full original at the same coordinates using the same `original outside mask + edited pixels inside mask` rule from above, with feathered edges at the crop boundary to avoid a visible seam. The user always sees a full-face result regardless of what was sent to the API — cropping is invisible to them if done correctly.

**Equivalence test (required before this can ship, part of the Phase 1 spike):**

For every test image, generate the same edit two ways:

1. full-frame send
2. padded-crop send + composite

Compare both against the same Section 27 success criteria (identity preserved, edit realistic, no visible seam or mismatched tone). If cropped results are visibly worse, or even ambiguously worse, on **any** test case, cropping is rejected for MVP — not "usually fine," no measurable quality gap, full stop. Only promote cropping to production once crop and full-frame are indistinguishable across the full test set.

If multiple change regions in one job are not adjacent (e.g. eyes and lips), and cropping has passed the equivalence test, prefer one padded crop covering both regions over two separate calls, if the provider supports multi-region masks in a single request — test this in the same spike rather than assuming it works.

Pricing model also matters here: per-megapixel or per-token providers see savings scale with crop area; providers billed by fixed resolution preset (e.g. discrete size tiers) only save when the crop lets you drop to a cheaper preset. Confirm which applies to the chosen provider before counting on savings.

---

## 18. Image Alignment

Original and refined images must align exactly.

The comparison slider will expose tiny geometry differences.

Alignment is guaranteed primarily by the compositing step in Section 17 (`final image = original outside mask + edited pixels inside mask`): pixels outside the mask are copied unchanged, so they are pixel-identical by construction and cannot drift.

This section is therefore a **validation guard**, not a second rendering step. Before returning a result, confirm the compositing actually held:

- confirm output image dimensions match the original exactly (no implicit resize/crop by the provider)
- run a landmark check to confirm eye/lip positions outside the intended edit region did not move
- if the provider only supports full-image regeneration (no mask compositing available), treat this as a Phase 1 blocker per Section 17 — do not attempt to fix misalignment after the fact with a second alignment/warp pass, as that reintroduces the risk it's meant to catch

The client must receive two same-size images.

---

## 19. Quality Validation

After editing, validate automatically.

### Identity consistency

The refined face must remain the same person.

### Geometry consistency

Check landmark deviation outside intended edit regions.

### Outside-mask consistency

Regions that were not edited should remain effectively unchanged.

### Crop-boundary consistency (only applies if cropped-send is enabled per Section 17)

If the cost-optimized cropping path is ever enabled, this is a distinct failure mode from mask-edge quality and must be checked separately: verify there is no visible seam, tone mismatch, or lighting discontinuity at the crop boundary itself, not just at the mask edge. A clean mask edit with a bad crop seam should still fail validation.

### Edit visibility

The intended modification should actually be visible.

If validation fails:

```text
retry once
```

The retry must vary something about the generation call (e.g. seed, or a slightly adjusted prompt/mask tolerance). An identical retry against an identical input is likely to fail the same way and simply doubles cost for no additional chance of success.

If retry fails:

return a `status: "failed"` result (see Section 13) with a stable `errorCode`.

Do not regenerate indefinitely.

---

## 20. Result Slider Implementation

Client-side only.

Render:

```text
Original Image
+
Refined Image overlay
```

Use clipping based on:

```text
sliderX
```

Conceptually:

```text
ZStack
  OriginalImage
  RefinedImage clipped from left to sliderX
  Divider at sliderX
```

Requirements:

- drag gesture
- smooth 0–100% movement
- default 50%
- no image reload during drag
- full original and full refined visible at slider extremes
- accessible alternative to the drag gesture (e.g. VoiceOver-exposed increment/decrement or a "swap" toggle between full original/full refined), since a pure drag gesture is not usable with VoiceOver

---

## 21. Annotation Model

Each accepted change should contain enough information for the client to render the guidance.

Example:

```json
{
  "area": "eyeliner",
  "annotation": {
    "type": "arrow",
    "normalizedPoints": [
      [0.62, 0.38],
      [0.68, 0.35]
    ]
  }
}
```

Use normalized coordinates:

```text
0.0–1.0
```

Supported MVP annotation types:

```text
arrow
line
region
outline
```

---

## 22. State Management

MVP does not require Redux.

Use:

- React hooks
- simple React context only if needed

Active session:

```ts
type RefinementSession = {
  localImageUri: string;
  refinementId?: string;
  originalImageUrl?: string;
  refinedImageUrl?: string;
  changes?: RefinementChange[];
  liked?: boolean;
};
```

No permanent user state.

---

## 23. Analytics

Track anonymously:

```text
app_opened
photo_selected
photo_rejected
refinement_started
refinement_completed
refinement_failed
result_viewed
slider_used
result_liked
result_disliked
details_viewed
```

Important metrics:

```text
generation success rate
like rate
details-view rate
repeat-session rate
```

No custom database required for MVP analytics.

Analytics must remain identifier-free (no device ID, no IDFA) for MVP. If any persistent or cross-app identifier is added later, Apple's App Tracking Transparency prompt requirement applies — treat that as a trigger for a privacy review, not a routine analytics change.

---

## 24. Privacy

Makeup photos are personal images.

MVP requirements:

- private storage
- temporary URLs
- configurable auto-delete
- no public image URLs
- no persistent user identification
- do not retain images unnecessarily
- clearly state image-retention behavior
- provide a clear privacy policy before public release

### Biometric data review (new, blocking before public release)

Face photos may be treated as biometric data under some regulations (e.g. Illinois BIPA, GDPR special-category data), independent of how briefly they're retained. Before public release:

- confirm what the AI provider(s) do with submitted images (training use, retention, sub-processors) and get this in writing where possible
- confirm whether biometric-specific consent language is required in the jurisdictions the app will be available in
- do not rely on "we delete it quickly" alone as the compliance answer

This is a legal review item, not just an engineering one — flag it early rather than at App Store submission time.

Future account creation should not change the principle that users control their photos.

---

## 25. Error Codes

Define stable application errors.

Examples:

```text
NO_FACE
MULTIPLE_FACES
FACE_TOO_SMALL
IMAGE_BLURRY
IMAGE_TOO_DARK
IMAGE_TOO_BRIGHT
UNSUPPORTED_IMAGE
ANALYSIS_FAILED
IMAGE_EDIT_FAILED
QUALITY_CHECK_FAILED
UPLOAD_FAILED
NETWORK_ERROR
```

Do not expose raw provider/model errors to the mobile client.

---

## 26. Future Features

Architecture should permit later addition of:

### Accounts

- Sign in with Apple
- persistent history

### Payments

- subscriptions
- generation credits

### Makeup inventory

User uploads products they own.

### Personalized recommendations

Learn from previously accepted/rejected refinements.

### Reference look

User uploads makeup inspiration.

### Style matching (new)

Match a user's current makeup to the closest of a small set of predefined style profiles, and ground the refinement planner's suggestions in the delta between the user's makeup and the matched style, rather than open-ended reasoning alone.

Out of scope for MVP: there is no style library to match against yet, and none should be hand-authored speculatively before real usage exists.

Data strategy when this is picked up: derive style profiles from real usage rather than guessing up front. Anonymous `MakeupAnalysis` outputs (Section 15) already generated by MVP traffic can be clustered offline into natural style groupings once there's sufficient volume, producing a library grounded in what users' makeup actually looks like rather than an editorial guess. This requires persistence of analysis outputs beyond the current session-only model (Section 11) and is not viable before Phase 4 traffic exists.

Guardrail if built: style-matching must only select which already-allowed technique to suggest (per Section 5's allowed refinement list) — it must not be used to justify changes outside that list, such as literal eye-size/shape changes. "Make eyes look bigger," for example, means an eyeliner/eyeshadow technique that creates that illusion (Section 16), never a geometric edit to the image.

### Android

React Native shared app should be reusable.

The AI pipeline and backend should require no Android-specific change.

---

## 27. Development Order

### Phase 1 — Local Technical Spike

Do not build the real app first.

Test:

```text
photo
→ analysis
→ planned changes
→ localized edit
→ refined photo
```

Use a small internal test set.

Success criteria (required — MVP does not ship without these):

- a mask-generation approach (landmark-based or segmentation-based, per Section 17) has been selected and works reliably on the test set
- the chosen AI provider(s) confirmed, in writing where possible, that localized real-face editing for this use case is permitted under their policy (see Section 17)
- face remains unchanged
- edits look subtle
- eye and lip edits look realistic
- non-edited regions remain stable

Do not proceed to Phase 2 until all of the above are true. If no provider/approach combination clears the policy and technical checks, stop and revisit the design.

### Optional experiment: cropped-send cost equivalence test

Run in parallel with the required criteria above, not as a blocker to Phase 2. On the same test set, generate each edit both full-frame and via padded-crop-and-composite (Section 17), and compare against the required criteria above. Enable cropping in production only if results are indistinguishable across the full test set — otherwise ship full-frame for MVP and leave cropping disabled.

---

### Phase 2 — Backend

Implement:

- FastAPI
- upload
- validation
- analysis
- planner
- image edit
- quality check
- temporary storage
- response contract

---

### Phase 3 — iOS App

Implement:

- Expo project
- photo picker/camera
- upload
- loading state
- draggable slider
- Like / Dislike
- details page
- annotations

---

### Phase 4 — TestFlight

Add:

- analytics
- crash reporting
- privacy text
- TestFlight distribution

Collect real-user feedback before adding major functionality.

---

## 28. Acceptance Criteria

MVP is complete when:

### Upload

User can take/select one selfie.

### Processing

A valid image reaches backend and produces a result.

### Refinement

System generates exactly one refined photo.

### Identity

The user clearly remains the same person.

### Subtlety

No dramatic makeup or facial transformation occurs.

### Comparison

User can continuously drag between original and refined image.

### Feedback

User can like or dislike the result.

### Explanation

If liked, user sees at most 3 concrete adjustments.

### Annotation

At least one adjustment can be visually indicated on the user's original photo.

### Persistence

No database is required.

### Architecture

Database, accounts, subscriptions, and Android can be added later without rewriting the core AI pipeline.

---


## 29. Coding-Agent Instructions

When implementing this design:

1. Do not add features outside MVP scope.
2. Do not add authentication.
3. Do not add a database.
4. Do not implement Android-specific UI yet.
5. Keep React Native code cross-platform unless a capability genuinely requires iOS-specific code.
6. Keep AI vendors behind provider interfaces.
7. Keep storage behind a storage interface.
8. Keep future persistence behind repository interfaces.
9. Use strict TypeScript types on the mobile client.
10. Use Pydantic models on the backend.
11. Do not return arbitrary unstructured AI text from backend APIs.
12. Validate model output before using it.
13. Keep image-processing modules independently testable.
14. Optimize for a small working MVP rather than architecture complexity.
15. Prefer clear code and small modules over premature abstractions.
16. Do not implement future database entities yet.
17. Do not generate more than one refined image per request in MVP.
18. Preserve original image pixels outside intended edit regions whenever possible.
19. Treat identity preservation and subtlety as hard product requirements.
20. Build the local technical spike before the complete mobile UI.
21. Do not build `/v1/refinements` as a single blocking call — implement job creation + polling as specified in Section 13.
22. Implement `completed_no_changes` and `failed` as first-class result states in both backend and mobile client, not as afterthought error handling.
23. Do not implement a second image-alignment/warp pass on top of mask compositing — see Section 18.
24. Run cheap image-quality pre-checks (Section 14) before any paid AI call, not after — reject unusable images without spending on analysis or generation.
25. Resize/downscale images to the minimum resolution actually needed before sending to any paid AI call.
26. Combine the makeup-analysis and refinement-planning steps into one AI call where the chosen provider's quality allows it (Section 15/16), rather than defaulting to two separate calls.
27. When a job has multiple change regions (e.g. eyeliner + lips), send them as one edit call with multiple mask areas where the provider supports it, not one call per change.
28. Rate-limit refinement creation per device/IP even though MVP has no accounts (Section 4) — this is an abuse-prevention requirement, not optional polish, since nothing else bounds cost on an unauthenticated endpoint.
29. Make `POST /v1/refinements` idempotent on a hash of the uploaded image, so a client retry after a timeout reuses the in-flight/completed job instead of creating a duplicate paid job.
30. Delete stored images promptly after the feedback event or the short default retention window (Section 12) — do not default to the longer debugging ceiling in production.

---

## 32. Suggested First Coding-Agent Task

Start with Phase 1 only.

Prompt:

```text
Read DESIGN.md completely.

Implement only Phase 1: Local Technical Spike.

Do not build the mobile app yet.
Do not add authentication or a database.
Do not add features outside DESIGN.md.

Create a minimal Python pipeline that accepts one local selfie,
runs makeup analysis and refinement planning through provider interfaces,
performs a localized image edit,
and writes:
1. the refined image,
2. structured JSON describing the proposed changes.

Keep all model providers swappable.
Add a README section explaining how to configure and run the spike.
```

Do not ask the coding agent to implement the entire product in one pass. Build and validate the image pipeline first.
