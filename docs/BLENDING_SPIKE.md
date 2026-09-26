# Phase 1 amendment: generate the technique, control its presentation

The generated candidate should demonstrate the full, clearly visible makeup
technique. The generation prompt does not ask for a small or subtle edit and
no longer includes the plan's `severity: subtle` or understated application
instructions. Planning still limits which techniques are allowed, keeps the
same overall makeup style, and can return no changes.

The final presentation is controlled in code:

```
alpha(x, y) = blend_strength × feathered_mask(x, y) / 255
final = round(original + alpha × (candidate - original))
```

The original and candidate are first interpreted in sRGB. Interpolation uses
encoded sRGB channel values, not linear-light values; this convention is fixed
so experiments are reproducible. Strength is a fraction in [0, 1], not a
perceptual percentage or a real-world pigment amount. Every pixel outside the
mask stays exactly unchanged. Mask feathering is applied once.

`0.5` is an experimental starting point, not an empirically selected product
default. `--blend-strength` is a developer spike parameter, not a new user-facing
makeup-control feature. The product still returns one refined photo.

## Validation in both directions

Before compositing, verify dimensions and facial landmarks on the candidate,
including landmarks inside the mask. A displaced eye or lip cannot be repaired
by reducing opacity: blending may introduce doubled contours. The final image
also receives the existing outside-mask and protected-landmark checks.

Each edited region must pass a numerical band after blending. Initial values:

- Mean absolute RGB-channel delta at least 2 and at most 35 (8-bit values).
- At least 20% of the region's mask support has a mean channel delta of 3 or more.

These are uncalibrated guards. They measure changed pixels, not useful makeup,
identity, realism or perceptual visibility. Small wings and broad eyeshadow
regions may require different calibrated limits. One active region cannot hide
an unchanged second region. Empty masks fail.

If a generated candidate is effectively unchanged or geometrically invalid,
the ordinary bounded generation retry may apply. If the candidate is usable
but the final blend is too weak/strong, return `EDIT_TOO_WEAK`/`EDIT_TOO_STRONG`
without another generation call. Keep the geometry-checked candidate so the
blend can be adjusted offline. Do not automatically turn strength up until
numerical tests pass and call that a successful result.

## Run the experiment

From the project root, generate one new candidate with the usual arguments,
adding `--blend-strength 0.5 --max-edit-attempts 1` to bound the experiment.
The CLI saves `original.png`, `candidate-1.png`, `mask.png`, per-area masks and
`candidate.json`, even if the blend subsequently fails strength validation.
The raw candidate is an intermediate diagnostic image, not the final result.
Its pixels outside the mask may differ and must never be presented as the
finished refinement.

Then run this locally, with no credentials or API calls:

```sh
.venv/bin/python -m makeup_refine.sweep outputs/your-new-trial \
  --output outputs/your-new-trial-calibration \
  --strengths 0.3 0.5 0.7 \
  --landmark-model models/face_landmarker.task
```

Open `index.html` in the output folder. It compares the original with all three
strengths; each has a before/after report and matching close-up. Record whether
the technique is visible, natural, identity-preserving and reproducible in
`calibration.json`. `selectedStrength` intentionally starts null. Repeat on a
consented test set before choosing a product value; do not tune solely to one
photo or to the numerical band.

Supplying `--landmark-model` rechecks candidate geometry and checks landmarks on
every blended variant locally. Without it, the report explicitly labels geometry
as not checked in the sweep. Geometry failures are flagged, never repaired by
warping or silently accepted at lower opacity.

To reuse the same analysis/plan in a controlled generation experiment, pass
`--plan-file path/to/plan.json` to `makeup-refine`. The file must match the `Plan`
schema (`analysis` and `changes`); it is validated before use and skips the paid
analysis call. This is for reproducible local experiments, not user-supplied
unvalidated instructions in a future backend.

All three variants come from exactly the same candidate, masks, and color
transform. This avoids confounding blend strength with generation randomness.
No additional model calls occur during a sweep. No images are uploaded.

Older trials 001 and 002 did not retain the raw generated candidate. Their
already-composited outputs cannot support a valid full-strength experiment;
reusing them would compound feathering and only weaken an already weak edit.
A fresh candidate is needed. All calibration images stay in ignored local
`outputs/` folders until deleted, like the rest of the spike.
