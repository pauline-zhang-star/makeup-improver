# Technique Mapping Table (v1.3 — adds style polish toward three visible areas)

**Companion file:** [`src/makeup_refine/technique_mapping_table.json`](../src/makeup_refine/technique_mapping_table.json) mirrors every entry in this document in machine-readable form (ids, trigger conditions, instruction templates, caps). Load that file directly rather than transcribing the markdown tables below by hand — hand-transcription is a likely source of copy errors. This markdown file is the source of truth for *content and reasoning*; the JSON file is the source of truth for *exact field values* and should be regenerated from this document if the two ever disagree.

## Purpose

This table is the controlled vocabulary the refinement-planning AI call (Section 16 of the main design doc) selects from. It replaces free-text generation with matching against pre-vetted, human-curated technique candidates.

**How it fits the pipeline:**

```
photo
→ detection (facial landmarks + color analysis)
→ measured features (e.g. eye_aspect_ratio, inter_eye_distance, lip_skin_contrast)
→ match measured triggers and assess which anatomical regions are visible
→ local rules retain measured matches, then add style-polish techniques toward 4 planned regions
→ keep at most 7 techniques in total
→ AI must cite which measured feature + threshold justified each suggestion (traceability requirement)
→ localized edit call executes the instruction
```

**Design principles this table follows** (do not violate when extending it):

1. Trigger conditions are continuous, measured facial/color features — never skin tone, ethnicity, or any demographic label.
2. Color adjustments are always relative deltas against the user's own detected color value — never a fixed target color/shade.
3. If no measured trigger passes, only a listed style-polish technique may be added in a confidently visible region. Never claim a facial deficit as its reason.
4. Every technique must be reversible/non-permanent makeup guidance, not a geometry change to the face itself.
5. Test set validation (Phase 1) must confirm each trigger's measured threshold performs consistently across a range of skin tones and face shapes — this table assumes detection is reliable, it does not compensate for detection bias.

---

## Rules for implementing this table (read before writing selection logic)

**Cross-region selection cap.** The product owner revised the limit to **7** per job, across *all* regions combined, not per region. This overrides the earlier limit of 3 in the main design doc. A single photo can match entries in several regions at once (e.g. brows + eyeliner + lips), producing more matches than the cap allows. Selection logic must therefore:
1. Evaluate every region's trigger conditions independently and collect all matches.
2. Apply each region's own mutual-exclusivity rules first (e.g. `lips_01` vs `lips_04`) to narrow matches within a region.
3. If more than 7 matches remain across all regions, rank by `detection_confidence` (highest first) and keep the top 7. Do not default to a fixed region priority order (e.g. always eyes before lips) — this biases every result toward the same regions regardless of what the photo actually needs.
4. If measured matches cover fewer than 4 distinct regions, add the v1.3 style-polish techniques below in confidently visible regions toward 4 planned regions. This leaves room for one edit that fails to appear while aiming for 3 *visibly changed* areas. These are positive styling options, not claims that a feature is defective. If fewer regions can be assessed confidently, return fewer. Never fill to 7 for its own sake.

**Product-owner revision:** aim for at least three *visibly changed areas* on a usable selfie, while retaining the maximum of seven techniques. Planning aims for four distinct areas when visible. A selected technique is still only an intention; post-generation comparison must verify what actually appeared. The trial thresholds remain uncalibrated.

### v1.3 style-polish entries

These entries require anatomical region visibility with confidence at least 0.85, not a deficit threshold. They are considered after measured-trigger entries, in this order, only when needed toward four distinct planned regions. They use placement intensity caps and the same identity safeguards as other entries. If blush is not confidently visible, the selector may use the conservative brow-edge or lower-lip-center fallback below; these are visibility-only styling options and do not assert a defect.

| id | region | technique | instruction |
|---|---|---|---|
| `eyeliner_05` | eyeliner | soft_outer_lash_definition | Trace a fine tapered line along the outer third of the upper lash line and lift its tip slightly; keep the inner corner soft. |
| `blush_01` | blush | high_outward_cheek_blend | Sweep a soft blush high on the outer cheeks and blend it toward the temples, coordinated with existing lip color. |
| `eyeshadow_07` | eyeshadow | soft_outer_lid_blend | Blend a soft midtone over the outer third of the upper lid, fading gently upward while leaving the inner lid light. |
| `brow_06` | brows | define_lower_edge | Slightly sharpen the lower edge of the existing brow without moving its edge. |
| `lips_02` | lips | center_highlight | Add a very thin highlight to the center of the lower lip to suggest fullness, without altering lip outline. |

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
| eyeliner_02 | downturned or elongated eye shape | `eye_tilt_angle` / `eye_aspect_ratio` | outer_wing_lift | "Extend the eyeliner along the lower lash line slightly upward at the outer corner." |
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

## JSON schema (for direct use in the planning AI's structured output / function-calling definition)

```json
{
  "region_id": "eyeliner | eyeshadow | brows | lips | blush | nose_contour | foundation",
  "technique_id": "string — must match an id in this table",
  "measured_feature": "string — the detected value that triggered this match",
  "measured_value": "number — the actual detected value",
  "threshold_used": "number — the trigger threshold from this table",
  "intensity": "number 0.0–1.0 — feeds into compositing blend_strength, not into how hard the edit call tries",
  "instruction_text": "string — filled from instruction_template, may be lightly reworded but must preserve technique meaning",
  "adjustment_type": "placement | color",
  "color_delta": {
    "color_space": "OKLCH",
    "delta_lightness": "number, |value| <= MAX_DELTA_L",
    "delta_chroma": "number, |value| <= MAX_DELTA_C",
    "delta_hue_degrees": "number, |value| <= MAX_DELTA_H_DEGREES"
  },
  "detection_confidence": "number 0.0–1.0 — undertone_confidence or iris_detection_confidence for hue-based entries"
}
```

Each output object must be traceable to exactly one table row (`technique_id`). The planning AI should not be permitted to emit `instruction_text` without a matching `technique_id` — reject and drop the suggestion server-side if the pair doesn't resolve to a table entry.

---

## Open items for Phase 1 spike

- Confirm exact numeric thresholds for every `measured_feature` (this table intentionally leaves them as "above/below threshold" — the actual cutoff values are empirical and must come from spike testing against a skin-tone/face-shape-diverse test set, per Section 27).
- Confirm `lip_skin_contrast_ratio` and `under_eye_darkness_score` detection remains reliable across a range of skin tones specifically — these are the two features most likely to be affected by known bias patterns in vision models, flagged separately for priority testing.
- `[COLOR]` entries: `color_delta` must be present when `adjustment_type` is `color`, and the server must reject any object whose deltas exceed the caps. Tune `MAX_DELTA_L`, `MAX_DELTA_C`, `MAX_DELTA_H_DEGREES` empirically in Phase 1. The placeholder values in the Color adjustment rules are guesses.
- Undertone estimation (`undertone_confidence`) and iris detection (`iris_detection_confidence`) are the least reliable measurements in this table. They are lighting-sensitive and likely to vary across skin tones and eye colors. Test them first, on the diverse test set, before enabling `lips_03`, `eyeshadow_05`, `eyeshadow_06` and `brow_03`. If the lighting gate fails often, ship MVP with only the lightness/chroma color entries and leave hue shifting disabled.
- Brows are a new region relative to the original three-region design (Section 16 of the main design doc). The product owner has confirmed brow shape and color are important, so treat brows as in MVP scope. The main design doc's allowed-region list (Sections 5 and 16) must be updated to include brows when the doc is next revised.
- Brow detection is the main technical risk for this region. Light, blond or gray brows have low contrast against the skin, sparse brows are hard to segment as hair, and bangs, glasses or hats can occlude them. Test these cases specifically, on the diverse test set, before enabling any brow entry. Confirm `brow_density_gap_score` and `brow_hair_lightness_gap` are reliable across skin tones and brow colors.
- Tune the brow geometric caps (`MAX_BROW_MASK_MARGIN_IED`, `MAX_TAIL_EXTEND_IED`, `MAX_THICKNESS_INCREASE_RATIO`) empirically. The placeholder values are guesses.
- Confirm the brow drift validation (Brow-specific rules, item 5) catches real drift without failing normal edits, and keep `brow_07` disabled until it does.
- Evaluate deterministic recolor versus generative edit for `[COLOR]` entries (Color adjustment rules, item 7).
- Nose contour and foundation regions are new relative to the original three-region design (Section 16) — confirm these are in intended MVP scope before implementation, or move them to Section 26 (Future Features) if not.
- Table is intentionally small (3–4 entries per region). Expand only after real usage/feedback data (Section 23) identifies gaps — do not pre-build exhaustive coverage speculatively.
