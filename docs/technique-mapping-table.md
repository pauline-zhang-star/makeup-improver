# Technique catalog (v1.6 vocabulary; model_visual_reasoning_v1 planning)

The JSON companion `src/makeup_refine/technique_mapping_table.json` supplies stable technique IDs, instructions, enabled flags, conflicts and rendering caps. Current selection is implemented in `src/makeup_refine/model_planning.py`; see [the model planning flow](MODEL_PLANNING_FLOW.md).

**The trigger_condition / measured_feature columns below are historical applicability descriptions, not production admission thresholds.** The JSON recipe, baseline and trigger metadata remains for [offline historical audits](LEGACY_SELECTION_FLOW.md). Production does not expose these score thresholds or fixed recipes to the planning model.

## Active flow

Original selfie + optional style → model proposes a coordinated look from this catalog → local code validates proposals → bounded image generation → compare actual images → explain actual changes.

The model records what it sees, why each technique fits the whole look and how to apply it. It can preserve areas already suited to the look. Code keeps model priority and validates catalog membership, disabled entries, visibility, mutual exclusions, rendering caps and color-reference reliability. It never fills a quota, replaces the model's deltas, or adds a fixed style recipe. At most seven proposals are permitted. Four useful changes are an aspiration, not a hard minimum.

A visibility confidence of 0.85 is still an availability gate; it is not a calibrated beauty score. Geometry is checked with local landmarks and bounded masks. Color deltas and placement intensities remain bounded rendering controls, with no claim of professional calibration.

### Art-direction review against professional references

These style names are useful consumer choices, not standardized technical categories. The qualitative direction is now differentiated as follows: **Natural** uses sheer skin-like finishes and soft, low-contrast definition; **Work / Polished** uses tidy neutral definition and restrained cheek/lip color; **Korean Soft** uses diffused eyes, soft natural brows, apple blush closer to the nose, and center-to-edge gradient lips; **Fresh** uses a light apple flush and lively but balanced lips; **Date Night** uses a softly defined brow to frame the stronger outer-eye definition and richer coordinated lip; **Sophisticated** favors controlled contrast and precise tapered placement; **Soft Glam** builds luminous, blended dimension in layers. The mask changes the cheek target using facial landmarks; it does not yet classify face shape, so these are style cues, not rigid rules for every person.

The recipe is the visual direction selected by the user; measurements only decide whether its regions can be safely used. Date Night therefore may select an outer wing and deeper outer-corner shadow even when eye tilt and crease measurements do not call for those as corrective techniques. The eye aperture stays protected, and these techniques cannot reduce measured eye opening. If a recipe region is occluded or low-confidence, it is skipped. Style lip color uses a capped relative delta on the existing lip color, not a shade target.

This review follows professional-artistry guidance that everyday makeup should enhance rather than transform, workplace makeup should keep attention on the person, Korean-inspired looks often use near-center apple blush and feathered gradient lips, blush location changes the visual effect, and soft glam depends on diffused blending rather than hard shapes ([M·A·C artistry direction](https://www.maccosmetics.com/blogs/mac-trend/no-makeup-makeup), [Bobbi Brown interview makeup](https://www.bobbibrowncosmetics.com/how-to-polished-interview-makeup), [Allure interview with Korean makeup artist Ko Won Hye](https://www.allure.com/story/how-to-do-chok-chok-korean-beauty-no-makeup-makeup), [Allure on professional blush placement](https://www.allure.com/story/how-to-apply-blush-techniques-used-by-makeup-artists), [Allure soft-glam guide](https://www.allure.com/story/soft-glam-makeup-guide-steps)). Rae Morris describes *Makeup Masterclass* as a 431-page instructional reference used by makeup schools, and her masterclass material highlights adapting technique to different eye shapes and bone structures ([book](https://raemorris.com/products/makeup-masterclass), [professional training](https://raemorris.com/products/sydney-masterclass-28-april-2026), [Rae Morris biography](https://raemorris.com/pages/about-rae-morris)). These sources support broad application principles; they do not supply the numerical thresholds or multipliers in this prototype.

| id | region | technique | instruction |
|---|---|---|---|
| `eyeliner_05` | eyeliner | soft_outer_lash_definition | Trace a fine tapered line along the outer third of the upper lash line and lift its tip slightly; keep the inner corner soft. |
| `blush_01` | blush | style_aware_cheek_blend | Apple placement for Natural, Korean Soft and Fresh; more outward placement for other named styles, always softly blended and face-aware. |
| `eyeshadow_07` | eyeshadow | soft_outer_lid_blend | Blend a soft midtone over the outer third of the upper lid, fading gently upward while leaving the inner lid light. |
| `brow_06` | brows | define_lower_edge | Slightly sharpen the lower edge of the existing brow without moving its edge. |
| `brow_08` | brows | soft_hairlike_brow_definition | Korean Soft only: add soft hairlike strokes inside the existing brow without carving its lower edge or imposing a shape. |
| `lips_02` | lips | center_highlight | Add a very thin highlight to the center of the lower lip to suggest fullness, without altering lip outline. |
| `nose_02` | nose_contour | bridge_highlight | Apply a thin highlight down the center of the nose bridge to add dimension. |
| `foundation_02` | foundation | highlight_points | Add a small amount of highlight at the top of the cheekbone and down the nose bridge center. |

**"AND" in a trigger condition means all listed conditions must independently pass.** If any one condition in a multi-part trigger (e.g. threshold check + confidence check + detection check) fails, the whole entry does not match — skip it, do not partially apply it or substitute a default value for the missing condition.

**Confidence gating is universal, not just for `[COLOR]` entries.** Every trigger condition depends on some detected/measured value having a `detection_confidence`. If confidence for the relevant measurement is below threshold, treat the entry as not matched, the same as if the trigger condition itself failed — regardless of region or whether it's marked `[COLOR]`.

**`intensity` vs `color_delta` — they are not layered, and don't multiply together.** For `adjustment_type: placement` entries, `intensity` (0.0–1.0) is the only strength control and feeds the compositing `blend_strength` in Section 17 of the main design doc. For `adjustment_type: color` entries, `color_delta` is the only strength control, already capped per the Color adjustment rules — `intensity` is not used for color entries and should be omitted or ignored, not set to some derived value.

**Unit normalization must be consistent across all regions, not just brows.** Any measured feature expressed as a spatial size or distance (not just brow caps) must be normalized to inter-eye distance (IED) so it scales with face size in the photo, not raw pixels. This applies to `nasal_width_ratio` and any future region added to this table, even where a specific entry's row doesn't spell out the normalization basis. Treat "IED-normalized" as the default for every spatial threshold in this table unless a row says otherwise.

**Occlusion / visibility preconditions apply to every region, not just brows.** The brows section states this explicitly (glasses, bangs, hats), but the same principle holds for eyeliner, eyeshadow, lips and nose entries — if the relevant facial region isn't clearly visible in the photo (obstructed, extreme angle, etc.), skip that region's entries rather than matching against unreliable or extrapolated measurements.

**Technique `id` values are a stable contract, not free-form labels.** Feedback (Section 23 of the main design doc) is tracked per `technique_id`. Once an id ships, do not renumber, reuse, or reassign it to a different technique in a later table version — add a new id instead, even if an old one is later excluded. Excluded entries keep their id in the "Excluded" list (see each region) rather than being deleted, so historical references don't break.

---

## Color adjustment rules (apply to every color-changing entry)

Entries that change color rather than placement/depth are marked `[COLOR]` in the tables below. They are the riskiest entries in this table because they depend on color measurement, which is sensitive to lighting.

1. **Perceptual color space.** Work in OKLCH (or CIELAB). Express every color change as deltas `ΔL` (lightness), `ΔC` (chroma), `Δh` (hue angle in degrees) relative to the color detected on this user's photo. Never specify an absolute target color, shade name, or product.
2. **Every delta is capped.** Keep changes at the "temperature/brightness" level, consistent with the main design doc's rule against dramatically changing lipstick color (Section 5). Config constants, placeholder starting values only, not validated, to be tuned in Phase 1: `MAX_DELTA_L = 0.06`, `MAX_DELTA_C = 0.04`, `MAX_DELTA_H_DEGREES = 12`. If a suggestion would need a larger delta to matter, drop the suggestion. Do not clip it and present it as if it achieved the goal.
3. **Undertone is a continuous measurement, never a label.** Estimate skin undertone from a skin-region sample (e.g. cheek) as a continuous warm-cool value, with a confidence score. Never map it to a demographic category.
4. **Lighting gate for hue-based entries.** Undertone estimation is unreliable under color casts (warm indoor light, colored ambient light, heavy camera processing). Run a color-cast check on the image. If the check fails, or `undertone_confidence` is below threshold, disable all hue-shifting entries for that job (`lips_03`, `eyeshadow_05`, `eyeshadow_06`, `brow_03`). Lightness/chroma-only entries stay available.
5. **Mutual exclusivity.** Entries that move the same channel in opposite directions cannot both be selected in one job (e.g. `lips_01` brighten vs `lips_04` soften). At most one hue-shifting entry per region per job.
6. **Refine, do not add.** Eyeshadow color entries require existing eyeshadow to be detected (`eyeshadow_coverage` above minimum). If none is detected, do not suggest a hue shift. Suggesting a brand-new eyeshadow color is a style change and out of scope for this table.
7. **Execution option to evaluate in Phase 1.** Color-only entries can be executed as a deterministic recolor of the masked region (OKLCH transform that preserves texture and specular detail) instead of a generative edit call. This removes generative identity-drift risk for those entries and costs nothing per call. Placement techniques (extend wing, add highlight) still need the generative edit. This is an option to test, not a decision.

---

## Region: eyeliner

| id | trigger_condition | measured_feature | candidate_technique | instruction_template |
|---|---|---|---|---|
| eyeliner_01 | wide inter-eye distance | `inter_eye_distance` above threshold | inner_corner_emphasis | "Deepen the eyeliner slightly at the inner corner to visually narrow the distance between the eyes." |
| eyeliner_02 | downturned or elongated eye shape | `eye_tilt_angle` / `eye_aspect_ratio` | outer_wing_lift | "Extend a fine tapered wing from the outer third of the upper lash line slightly upward and outward; leave visible skin between pigment and the eye opening." |
| eyeliner_03 | hooded eyelid (crease covers lid) | `visible_lid_ratio` below threshold | thicken_lash_line | "Slightly thicken the eyeliner along the lash line so it remains visible when the eye is open." |
| eyeliner_04 | narrow inter-eye distance | `inter_eye_distance` below threshold | outer_extend_inner_taper | "Extend the eyeliner outward toward the outer corner; keep the inner corner thin or bare." |

## Region: eyeshadow

| id | trigger_condition | measured_feature | candidate_technique | instruction_template |
|---|---|---|---|---|
| eyeshadow_01 | deep-set eye socket | `socket_depth_estimate` above threshold | center_lid_highlight | "Apply a light highlight tone to the center of the upper lid to soften shadow depth." |
| eyeshadow_02 | monolid / flat lid structure | `crease_visibility` below threshold | outer_corner_deepen | "Blend a slightly deeper tone into the outer corner and outer crease area for added dimension." |
| eyeshadow_03 | wide inter-eye distance | `inter_eye_distance` above threshold | inner_corner_deepen | "Blend a slightly deeper tone into the inner corner to narrow the visual gap." |
| eyeshadow_04 | narrow inter-eye distance | `inter_eye_distance` below threshold | outer_corner_extend | "Extend eyeshadow blending toward the outer corner; keep inner corner light." |
| eyeshadow_05 `[COLOR]` | eyeshadow hue misaligned with skin undertone | `eyeshadow_undertone_hue_gap` above threshold AND `undertone_confidence` above threshold AND eyeshadow detected | hue_align_to_undertone | "Shift the eyeshadow hue slightly toward the warm or cool direction that harmonizes with the skin undertone (small relative hue delta, capped per Color adjustment rules)." |
| eyeshadow_06 `[COLOR]` | low contrast between eyeshadow color and iris color | `eyeshadow_iris_contrast` below threshold AND `iris_detection_confidence` above threshold AND eyeshadow detected | complement_iris_shift | "Shift the eyeshadow hue slightly toward the complement of the iris color so the eyes stand out (small relative hue delta, capped per Color adjustment rules)." |

## Region: brows

Brows are a high-importance region for this product, and they carry an identity risk. Brow position and angle strongly shape both perceived expression and perceived identity, so brow shape entries are limited to filling and defining inside the existing brow. They never relocate or reshape it.

### Brow-specific rules

1. **Edit mask = existing brow only.** Build the mask from the brow landmark polygon plus a small capped margin. A tail extension adds a capped extrapolated segment along the existing tail direction. Nothing outside that mask is edited.
2. **Geometric caps are normalized to inter-eye distance (IED)** so they scale with face size. Config constants, placeholder starting values only, not validated, to be tuned in Phase 1: `MAX_BROW_MASK_MARGIN_IED = 0.02`, `MAX_TAIL_EXTEND_IED = 0.06`, `MAX_THICKNESS_INCREASE_RATIO = 0.15`. A suggestion that needs more than the cap is dropped, not clipped.
3. **Excluded by design decision:** moving the brow up or down, changing arch height or arch angle, dramatic thickness change, and converting the brow to a different style (e.g. straight to arched). These reshape the face and are excluded for the same reason as lip peak adjustment. Do not add them back without revisiting the "no facial feature reshaping" rule (Section 5 of the main design doc).
4. **Visibility precondition.** Both brows must be visible (`brow_visibility` above threshold). If bangs, glasses, a hat or a hand hides a brow, skip the whole region for that job.
5. **Brow drift validation.** After editing, check that brow endpoints and arch peak on both brows stay within tolerance of the original, except for the capped tail extension. Outside-mask pixels must remain identical.
6. **Color entries** follow the Color adjustment rules above. The reference color is the user's hair color, measured from a hair-region sample (`hair_detection_confidence` must pass). Hair color is a continuous measured value, never a label.

### Color entries

| id | trigger_condition | measured_feature | candidate_technique | instruction_template |
|---|---|---|---|---|
| brow_01 `[COLOR]` | brow faint against the skin | `brow_skin_contrast` below threshold | deepen_brow_tone | "Deepen the brow color slightly relative to its current value (small relative lightness delta, capped) so the brows frame the eyes more clearly." |
| brow_02 `[COLOR]` | brow much darker than hair, reads harsh | `brow_hair_lightness_gap` above threshold AND `hair_detection_confidence` above threshold | soften_brow_tone | "Lighten the brow color slightly toward the hair color (small relative lightness delta, capped) to soften a harsh look." |
| brow_03 `[COLOR]` | brow hue misaligned with hair hue | `brow_hair_hue_gap` above threshold AND `hair_detection_confidence` above threshold AND lighting gate passes | brow_hue_align | "Shift the brow hue slightly toward the hair hue (small relative hue delta, capped) so brow and hair read as harmonious." |

`brow_01` and `brow_02` move the same channel in opposite directions and are mutually exclusive.

### Shape entries (fill and define inside the existing brow)

| id | trigger_condition | measured_feature | candidate_technique | instruction_template |
|---|---|---|---|---|
| brow_04 | sparse or gappy brow | `brow_density_gap_score` above threshold | fill_sparse_gaps | "Fill sparse gaps inside the existing brow outline with fine hair-like strokes that match the existing hair color and growth direction. Do not extend beyond the current brow boundary." |
| brow_05 | faded or short brow tail | `brow_tail_fade_score` above threshold | define_tail | "Define the brow tail by extending it slightly along its existing direction (capped extension). Keep the tail angle unchanged." |
| brow_06 | unclear lower brow edge | `brow_edge_definition` below threshold | define_lower_edge | "Slightly sharpen the lower edge of the brow so its shape reads more clearly, without moving the edge." |
| brow_07 | noticeable left-right brow asymmetry | `brow_asymmetry_score` above threshold AND both brows detected | balance_weaker_brow | "Fill or define only the weaker brow slightly so the pair looks more balanced. Do not move either brow's position or arch." |

`brow_04` and `brow_07` cannot both target the same brow in one job.

**`brow_07` ships disabled by default.** Asymmetry balancing is the highest identity-drift risk among the brow entries. Enable it only if Phase 1 shows no brow landmark drift beyond tolerance on the diverse test set.

---

## Region: lips

| id | trigger_condition | measured_feature | candidate_technique | instruction_template |
|---|---|---|---|---|
| lips_01 `[COLOR]` | low lip-to-skin color contrast | `lip_skin_contrast_ratio` below threshold | relative_tone_brighten | "Increase lip color saturation/brightness relative to its current detected value (relative delta, not a fixed target shade)." |
| lips_02 | low lower-lip volume appearance | `lower_lip_fullness_estimate` below threshold | center_highlight | "Add a very thin highlight to the center of the lower lip to suggest fullness, without altering lip outline." |
| lips_03 `[COLOR]` | lip hue misaligned with skin undertone | `lip_undertone_hue_gap` above threshold AND `undertone_confidence` above threshold | hue_align_to_undertone | "Shift the lip color hue slightly toward a shade that harmonizes with the skin undertone (small relative hue delta, capped per Color adjustment rules). Keep lightness roughly unchanged." |
| lips_04 `[COLOR]` | lip color overpowers the rest of the makeup | `lip_chroma_dominance_score` above threshold (lip chroma relative to eye-region and cheek chroma) | chroma_soften | "Reduce lip color saturation slightly relative to its current value so it balances with the rest of the look." |

**Excluded — do not implement, do not add to any active candidate set:**

| excluded_id | would-be trigger | reason for exclusion |
|---|---|---|
| lips_excluded_01 | lip peak / cupid's bow not well-defined | Borders on altering facial geometry rather than applying makeup color/technique — conflicts with the "no facial feature reshaping" rule (Section 5 of the main design doc). Do not add without revisiting that rule explicitly. |

## Region: nose contour (nose_contour)

| id | trigger_condition | measured_feature | candidate_technique | instruction_template |
|---|---|---|---|---|
| nose_01 | wide nasal base/nostril span | `nasal_width_ratio` above threshold | side_shadow_subtle | "Apply a very subtle shadow along both sides of the nose to visually narrow its width. Keep effect minimal." |
| nose_02 | low bridge prominence | `bridge_flatness_estimate` above threshold | bridge_highlight | "Apply a thin highlight down the center of the nose bridge to add dimension." |

**Note:** This region carries higher risk than eyeliner/eyeshadow/lips — contouring can read as reshaping if overdone. `intensity` for this region should default lower than other regions, and validation (Section 19) should weight this region's outside-mask/edge checks more strictly.

## Region: foundation (local highlight/concealer points only — NOT full-face)

| id | trigger_condition | measured_feature | candidate_technique | instruction_template |
|---|---|---|---|---|
| foundation_01 | under-eye darkness | `under_eye_darkness_score` above threshold | under_eye_local_brighten | "Apply light, localized concealer-style brightening strictly within the under-eye shadow area." |
| foundation_02 | low highlight-point definition | `cheekbone_highlight_estimate` below threshold | highlight_points | "Add a small amount of highlight at the top of the cheekbone and down the nose bridge center." |

**Scope constraint, non-negotiable:** This region is limited to small, localized points (under-eye triangle, cheekbone high point, nose bridge). It must never be implemented as full-face tone-matching, smoothing, or blemish removal — that would require a mask covering most of the face, which conflicts with the localized-edit architecture (Section 17) and sharply raises identity-drift risk. If "even out skin tone across the whole face" is ever requested as a feature, treat it as a separate, unapproved scope discussion — do not extend this table to cover it.

---

## Production planning schema

`LookDesign.model_json_schema()` is sent to the model. The response contains `look_direction`, seven anatomical `visibility` entries, `lighting_gate`, `color_references`, `proposals` and `preserved_areas`. A proposal looks like:

```json
{
  "technique_id": "brow_04",
  "observation": "Small gaps are visible toward the brow tail.",
  "style_reason": "Softly filling those gaps balances the richer evening lip.",
  "application": "Add fine strokes inside the existing brow outline.",
  "intensity": 0.4,
  "color_delta": null,
  "target_side": "both"
}
```

Color proposals instead provide a relative OKLCH delta and null intensity. Model application text supplements the canonical catalog instruction within its bounds. Final user instructions are still generated from the actual original/enhanced pair, not copied from this proposal.

## Open items for visual validation

- Test whether model observations and style choices are consistent across repeated analyses and varied skin tones, eye shapes, brow colors and existing makeup.
- Inspect actual visual improvement and style coherence on saved original/enhanced pairs. Passing structural validation does not establish either.
- Calibrate rendering caps and visibility/reference reliability with real examples; these controls do not eliminate all model mistakes.
- Validate sensitive hair/iris/undertone color references under varied lighting. Unreliable references must block affected hue techniques.
- Retain landmark checks, eye-opening protection, localized masks and texture preservation. A declared observation is not proof that the generated image followed it.
