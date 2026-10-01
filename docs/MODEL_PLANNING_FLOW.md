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
