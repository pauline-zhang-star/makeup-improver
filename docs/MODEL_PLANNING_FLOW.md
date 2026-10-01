# Current model planning flow

Version: `model_visual_reasoning_v1`. Applies to both Auto and all named styles.

1. The original selfie and optional style are passed to the planning model. Auto targets light, airy everyday makeup; Date Night targets richer evening makeup. Style owns finished intensity. Existing heavy makeup can be softened, while already suitable areas can be preserved. Named styles are not uniformly darker than Auto.
2. The model considers existing makeup and chooses up to seven catalog actions as one look. Each action needs a visible observation, a reason tied to the whole look, and a photo-specific application. The model chooses placement intensity or a relative color delta. It may preserve already-suitable areas or return fewer/no changes.
3. Code checks allowed IDs, disabled entries, duplication, preservation conflicts, mutual exclusions, region visibility, strength caps and color-reference reliability. It preserves proposal order. Rejected actions are logged with reasons; no automatic filler, replacement color, fixed recipe or aesthetic-score trigger runs.
4. Generation receives the original image, selected-technique mask, overall look direction, canonical instructions and bounded photo-specific applications. Direction text cannot authorize unselected edits. Rejected actions are not included in the selected instruction list.
5. Existing registration, face-proportion/eye-opening checks, protected pixels, texture protection and selected-region change checks run. The original and final images and draggable comparison remain as before.
6. A separate visual comparison creates actionable user steps only for the changes actually observed in the accepted image.

## Records and error behavior

- `techniqueAnalysis.analysis_schema`: `model_visual_reasoning_v1`; saves the full returned visual design, without aesthetic measurement scores.
- `techniquePlan.selection_method` and `planningMode`: distinguish new planning from historical threshold/recipe plans.
- `look_direction`, `preserved_areas`, `selected`, `rejected_proposals`: retain the model's design and the local validation result.
- Each selected action keeps `observation`, `style_reason`, `application`, model-chosen strength and `selection_basis=model_visual_reasoning`.
- `threshold_status=aesthetic_thresholds_not_used`; geometric and rendering bounds remain active.
- Missing observations, invalid structure or more than seven proposals fail planning. There is no automatic planning retry.
- If every proposed action is rejected, the pipeline returns `planning_rejected`, keeps the original and makes no edit/comparison calls. An intentionally empty valid proposal list returns `completed_no_changes`.
- Four areas remain a reporting/aspirational target, never a reason to fabricate proposals or reject an otherwise valid small plan.

## Historical compatibility

`TechniqueAnalysis`, `STYLE_TRIGGER_OVERRIDES`, fixed recipe/fallback data and `TechniqueCatalog.select()` remain available for historical offline replay. They are not called by `OpenAIProvider.plan_techniques()`. Old saved plans and slider reports remain readable. The table version remains 1.6 because the catalog vocabulary is unchanged; the new planning schema is versioned independently.

The offline replay script explicitly identifies new-schema designs as unsupported by the historical threshold audit. It does not turn model observations into invented measurements.

## Remaining limits

Visibility/reference confidence and observations are model assertions, not calibrated ground truth. Code validates structure and bounds, not whether a makeup judgment is aesthetically correct or the observation is true. Color/placement caps remain provisional; eye and identity preservation still need output checks. Photo-specific prose is constrained by the canonical catalog instructions and mask, but model compliance is not guaranteed. This implementation has mocked-provider and local validation tests; visual performance requires a fresh real-photo trial.


## Local comparison evidence

The accepted, registered original/final pair is compared without further warping or image generation. Each selected technique supplies its own mask support, mean absolute RGB delta, changed fraction (RGB delta >= 3/255), signed RGB channel change, and luminance-gradient change. Matching crops, split by image side for brows/eyes/cheeks, are sent with both full photographs in the same comparison call. No desired style, application prose or target strength is supplied to the comparator.

`comparisonEvidence` saves coordinates and diagnostics for explanation-only replay. A mean delta >= 2/255 and changed fraction >= 0.20 flags attention, not perceptual proof. Overlapping masks cannot identify the cosmetic responsible. The model must still classify all eight areas. `pendingChangeReviews` retains uncertain selected areas and numerical/visual disagreements, separately from confirmed instructions in the review page. No automatic image or comparison retry is added.

For historical results without evidence, `--retry-instructions DIR --landmark-model models/face_landmarker.task --vision-model MODEL` builds it using the established detector environment. Later retries reuse saved evidence; old results without a landmark model retain full-image comparison compatibility. Keep saved evidence with its original, unchanged image pair.

Validated on the saved Auto pair in `outputs/ai-trial-002-auto-local-comparison-20260930`: one comparison-only API call recovered eyeliner and blush in addition to brows, shadow and lips. Both PNGs remained byte-identical. This is one regression example, not a calibrated detection benchmark.


## Style includes intensity

The planning and generation prompts share the style target. They compare the input makeup to that target, allowing addition, preservation or reduction. Auto emphasizes soft brow edges, visible individual hairs, light eye definition and restrained lip color. Date Night defaults to richer coordinated definition, without automatically darkening every already-intense feature.

The existing catalog already supports `brow_02` (soften brow pigment) and `lips_04` (reduce lip chroma). The active validator rejects opposite-signed deltas for these techniques and `brow_01`; it never substitutes a new action or changes the proposed value. Existing caps, visibility/reference checks, masks and geometry gates remain unchanged. Measurable pigment reduction counts as a visible change, and the image-comparison prompt can describe reducing/blending existing product instead of always adding more.

These are product directions and semantic parameter checks, not claims about universal beauty standards. Automated tests verify prompt propagation, signed-delta validity and bidirectional pixel detection. The aesthetic effect still needs a new real-image test; this wording change does not retroactively alter saved results.


## Shared whole-look priority

`LOOK_HARMONY_PRINCIPLES` is included verbatim in both the planning and image-edit prompts. Within existing hard bounds, the objective is a harmonious result that approaches the selected style. Intensity serves this objective rather than being uniformly increased/decreased. The model compares brows, eyes, cheeks and lips together, coordinates temperature/depth/saturation/edges/finish, and can strengthen one feature while softening or preserving others. Harmony cannot excuse switching to generic natural makeup or crossing mask/geometry/technique limits.

The planner's `look_direction` must describe visual emphasis and supporting areas; each `style_reason` must explain how its direction and strength fit the style and the rest of the face. Auto's lightness describes the whole everyday impression, and Date Night's evening expression does not mandate heavy pigment everywhere. This is explicit model direction, not a numeric beauty score or a guarantee of aesthetic success. The final comparator remains grounded in the actual images, without receiving the intended style as evidence of success.


## Planning output contract

Planning uses strict JSON-schema output rather than JSON mode. The wire schema fixes availability/color-reference keys, makes all fields explicit, and separates placement and color techniques by catalog ID: a placement action requires numeric intensity and null color delta; a color action requires an OKLCH delta and null intensity. Missing/unreliable color references are reported with false availability. This prevents the observed Date Night format errors (both parameter types, `skin_undertone` instead of `undertone`, lowercase color-space identifiers) without inventing or repairing model-chosen values. Local semantic and safety validation still runs, and refusals/invalid responses still stop the call without automatic planning retries.

The wire schema follows [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Local string-length validation remains in place. This change does not guarantee correct aesthetic observations or image-generator compliance.


## Date Night brow planning correction

User feedback on the 2026-09-30 Date Night trial accepts the rendered look but rejects its planned brow-lightening rationale. The original has no applied brow makeup according to the user. Date Night now explicitly targets stronger evening makeup with clear brow shape supporting the eyes/lips. Bare or lightly made-up brows can receive gap filling, tail refinement or controlled edge definition when supported by the photo. Natural dark hairs alone do not justify `brow_02`; soft edges do not mean lighter color. Reduction requires an observation of identifiable excessive applied product and a reason it disrupts the evening look. This is a planning/rendering prompt correction, not a new image, fixed recipe, numeric aesthetic threshold, or retroactive alteration of the saved plan.

## Enforced brow-softening evidence gate

`LookDesign.brow_makeup_evidence` now carries a structured source classification, excess-product flag, detection confidence, visible product cues, observation and reason to reduce. It is nullable for other plans and historical schema compatibility; the strict API schema requires the field to be explicitly present. No questionnaire or additional API call is introduced.

The active validator requires this evidence for `brow_02`: `pigment_source=applied_makeup`, `excess_applied_product=true`, confidence at least the existing availability threshold (0.85), one or more product cues, and nonblank observation/reason. Missing evidence, natural hair, uncertain classification, non-excessive product and incomplete evidence have distinct rejection reasons. Natural darkness and "balance stronger eyes" do not independently satisfy this structured gate. The evidence is saved with the validation audit and accepted action. Other brow techniques remain available without evidence of existing product; no replacement technique is inserted automatically.

This checks consistency/completeness of model-reported evidence, not independent visual proof that a product is present. The model can still misclassify the photograph. Offline replay of the saved Date Night plan now rejects its unsupported `brow_02`; it leaves the accepted photo and historical plan untouched. Evidence and replay are in `outputs/brow-softening-validation-20260930/offline-replay.json`.

### Per-technique evidence (2026-10-01)

Every new proposal includes `structured_evidence`: anatomical region, current state,
pigment source, operation, purpose, confidence, observable cues, observation,
target effect, and style rationale. The strict API schema requires a non-null
object; locally, missing or insufficient evidence filters the proposal without
inventing a replacement. Invalid schema values still fail schema parsing.

Anatomical `visibility` is independent of makeup presence: bare visible eyelids,
cheeks and nose remain available. Balanced makeup may be adapted to the selected
style; adding makeup does not require declaring a natural feature defective.
`brow_01` darkening is enhancement, not removal of excess product.

Reduction requires identifiable excess applied product. This also checks actual
color deltas: positive brow lightness or negative lip chroma cannot evade the gate
by being named a hue adjustment. Natural pigmentation alone is insufficient.
Confidence retains the existing uncalibrated 0.85 floor; no new arbitrary nose
confidence threshold was introduced. Existing nose intensity limits still apply.

The old top-level `brow_makeup_evidence` remains readable for historical audit,
but cannot substitute for per-proposal evidence. Existing free-text `evidence`
lists remain compatible with consumers; structured evidence has its own key and
is displayed in the test report. Historical files are not silently rewritten.
These checks enforce reported consistency, not independent visual truth, beauty,
or proof of adherence by the image generator. Generation and final comparison
remain necessary. No live API validation is implied by the local regression tests.

### Pixel geometry recheck (2026-10-01)

Facial widths no longer use external eye-corner span as denominator. Paired
landmarks are converted to actual image pixels and aligned using one global
similarity fit on forehead/face-outline anchors, excluding brows, eyelids,
nostrils and lips. This changes measurement coordinates, never image pixels.
Central lid pairs are projected onto the original eye's normal; corners are
excluded. Values are now named `*Pixels`, with units and alignment stored in the
report. Historical ratio records are retained without reinterpretation.

Exact unchanged pixel support around both detected positions overrides apparent
landmark displacement for that measurement. Raw readings and crop boxes are
retained. Changed pixels do not prove changed anatomy. At-most-one-pixel
violations are labeled measurement uncertainty and still held for review; this
is a provisional diagnostic label, not permission to shrink eyes. Thresholds
for actual size change remain unchanged. This is still landmark-based, not
independent eyelid/iris segmentation, and face-outline anchors can also drift.

Cosmetic mouth width is diagnostic only (user-approved policy): lipstick and
liner may widen or narrow the perceived outline within the selected mask and
technique. Mouth-width values do not reject or request review. Mouth opening,
teeth visibility, expression, and other geometry checks remain protected.

### Input detail and compositing boundaries (2026-10-01)

Before paid planning, local eye/lip crops are downsampled (never upsampled) to
at most 160x80 and lightly smoothed before measuring Laplacian variance. Two
weak regions reject the input with a retake message. Initial experimental
floors: eyes 120, lips 35; these are not population-calibrated and may confuse
low contrast with blur. This does not independently detect beauty filters or
hair occlusion. Diagnostics expose all crop boxes, scores and thresholds.
The current IMG_0993 fails; IMG_7706 passes the local replay. More varied inputs
are needed for calibration, especially near the threshold.

The experimental inward-smoothstep compositor has been withdrawn after visual
review. Production again uses the preceding edge_safe_color_matched_composite
implementation. Input-detail rejection remains enabled before paid planning;
it returns an IMAGE_BLURRY error, inputRejected=true, retryAction=upload_clearer_photo,
and a user-facing retake message. Historical diagnostic images from the withdrawn
algorithm remain artifacts, not approved results. No previous test image is overwritten.
