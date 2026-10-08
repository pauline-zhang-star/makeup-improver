> Historical design record. Retired experiment commands and code described here were removed on 2026-10-07. Use [the current planning architecture](MODEL_PLANNING_FLOW.md) and [README](../README.md) for supported behavior.

# Archived threshold/recipe selection (inactive)

This section describes selection before `model_visual_reasoning_v1`. It is retained for historical offline replay, not used by the production provider.

# Technique Mapping Table (v1.6 — balanced Date Night recipe)

**Companion file:** [`src/makeup_refine/technique_mapping_table.json`](../src/makeup_refine/technique_mapping_table.json) mirrors every entry in this document in machine-readable form (ids, trigger conditions, instruction templates, caps). Load that file directly rather than transcribing the markdown tables below by hand — hand-transcription is a likely source of copy errors. This markdown file is the source of truth for *content and reasoning*; the JSON file is the source of truth for *exact field values* and should be regenerated from this document if the two ever disagree.

## Purpose

This table is the controlled vocabulary the refinement-planning AI call (Section 16 of the main design doc) selects from. It replaces free-text generation with matching against pre-vetted, human-curated technique candidates.

**How it fits the pipeline:**

```
photo
→ user selects an optional style (Auto is the default)
→ detect facial landmarks, visible regions and continuous color/shape measurements
→ Auto uses measured triggers and confidence ranking
→ a named style uses its style-specific technique rules; measurements gate visibility and safety
→ optional additions for named styles come only from that style's curated options
→ keep at most 7 techniques in total
→ record whether each technique came from the style recipe or a measured trigger
→ localized edit call executes the instruction
```

**Design principles this table follows** (do not violate when extending it):

1. Trigger conditions are continuous, measured facial/color features — never skin tone, ethnicity, or any demographic label.
2. Color adjustments are always relative deltas against the user's own detected color value — never a fixed target color/shade.
3. Auto uses general measured-opportunity selection. A named style uses its own rules to choose the makeup techniques that create that look; original-photo measurements, visibility, confidence and landmarks gate whether a selected technique is available and safe. Generic Auto trigger matches cannot be appended to a named-style plan. Never claim a facial deficit as the reason for a style technique.
4. Every technique must be reversible/non-permanent makeup guidance, not a geometry change to the face itself.
5. Test set validation (Phase 1) must confirm each trigger's measured threshold performs consistently across a range of skin tones and face shapes — this table assumes detection is reliable, it does not compensate for detection bias.

---

## Rules for implementing this table (read before writing selection logic)

**Cross-region selection cap.** The product owner revised the limit to **7** per job, across *all* regions combined, not per region. A single photo can produce candidates in several regions. Selection logic must therefore:
1. Auto ranks measured opportunities by confidence. A named style selects from its style-specific recipe and optional rule list. Recipe placements need visible anatomy, confidence and geometry safety, not a defect trigger; recipe colors use a capped relative delta on a confidently visible feature.
2. Apply each region's mutual-exclusivity rules (e.g. `lips_01` vs `lips_04`) so techniques in one area do not conflict.
3. For named styles, optional techniques must be listed for that style and pass its applicable rules. Do not append other generic trigger matches.
4. Keep at most 7 techniques. A style may have more than four when its look requires it; do not pad with unrelated techniques just to reach a quota.

**Product-owner revision:** aim for at least four *visibly changed areas* on a usable selfie, while retaining the maximum of seven techniques. Planning aims for four distinct areas when visible. A selected technique is still only an intention; post-generation comparison must verify what actually appeared. The trial thresholds remain uncalibrated.

### v1.4 style-polish entries

These earlier entries provide visibility-only placement options; v1.5 introduced named-style recipes instead of waiting for generic corrective matches to leave unused slots.

Auto uses the generic measurement-led selection flow. Named styles use their own curated technique rules, with photo analysis and landmarks checking region visibility, confidence, color caps, eye-opening limits and other geometry protections. A style technique does not require a measured “defect”; a generic Auto trigger cannot add an unrelated technique to the named-style plan. Color recipes remain small relative OKLCH deltas, require confidently visible lips and are never fixed product shades. Style intensity values and color deltas are provisional rendering controls, not professionally calibrated standards.

### Style technique rules

For named styles, the recipe column below is selected when its regions are confidently visible; it does not depend on defect thresholds. Optional techniques are curated per style and remain subject to their stated measurements. The selector never adds unrelated generic trigger matches. Auto keeps confidence-first measured selection. `style_baseline_styles` enables a placement only for its listed styles. All styles retain confidence, visibility, geometry, conflict and color-cap checks.

| style | primary style recipe / preference order | additional corrective trigger overrides |
|---|---|---|
| Auto | `eyeliner_05`, `eyeshadow_07`, `brow_06`, `lips_02`, `blush_01`, `nose_02`, `foundation_02` | None; default thresholds and confidence-first measured ranking |
| Natural | `eyeshadow_07`, `brow_06`, `eyeliner_05`, `lips_01`; then `lips_04`, `lips_02`, `blush_01`, `foundation_02`, `nose_02` | `lips_04`: chroma dominance >0.80 |
| Work / Polished | `brow_06`, `eyeliner_05`, `eyeshadow_07`, `lips_01`; then `brow_04`, `foundation_01`, `foundation_02`, `blush_01` | `foundation_01`: under-eye darkness >0.40; `brow_04`: density-gap score >0.78 |
| Korean Soft | `eyeshadow_07`, `blush_01`, `eyeliner_05`, `lips_01`; then `brow_08`, `foundation_02`, `nose_02` | `brow_08`: brow-edge definition < table threshold |
| Fresh | `blush_01`, `lips_01`, `eyeshadow_07`, `eyeliner_05`; then `brow_06`, `foundation_02`, `nose_02` | None |
| Date Night | `eyeliner_02` (.68), `eyeshadow_02` (.62), `brow_06` (soft lower-edge definition), `lips_01` (ΔC +.035), `blush_01` | No defect trigger for the recipe; selected regions must be confidently visible |
| Sophisticated | `brow_06`, `eyeliner_05`, `eyeshadow_07`, `lips_01`; then `brow_05`, `lips_03`, `nose_02`, `foundation_02` | `brow_05`: tail-fade score >0.65; `lips_03`: undertone hue gap >7° |
| Soft Glam | `eyeshadow_02` (.58), `eyeliner_05`, `blush_01`, `lips_01`; then `eyeshadow_07`, `brow_06`, `nose_02`, `foundation_02` | None required for recipe |

The intensity multipliers from v1.3 were removed. Their per-style percentages were not grounded in professional artistry references or image-set calibration; the named-style mask allowance remains the mechanism for broader placement. Trigger thresholds are still provisional engineering experiments, not professional standards or universal beauty measurements.

