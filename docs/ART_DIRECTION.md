# Aesthetic review

The user can see the three edits in placement trial 004 but does not prefer the
result to the original. Record it as a failed aesthetic result, even though its
pixel and landmark checks passed. The wing tips look blunt and the lip contour
looks excessively outlined. Lower opacity alone cannot fix those shapes.

The planner and renderer now share explicit art-direction constraints:

- Propose a correction for a visible issue, with a full-face reason for it.
- Keep liner connected and tapered, shadow edges graduated, and lip corrections
  blended inward without a dark perimeter.
- Do not use the entire mask just because it is editable. Do not force three edits.
- Generate a legible technique; control its final intensity through compositing.
- Preserve natural features and the existing style. A changed expression is not
  a makeup correction.

These prompt changes are implemented, but their effect has not yet been tested
with a new generated image. They are not an automatic aesthetic quality gate.

Next visual experiment: establish the user's desired look, then create a new
candidate on the same photo. Compare the original and candidate at equal size,
first at full-face scale and then in feature crops. Judge shape and edges before
tuning opacity. Do not spend generations sweeping opacity; reuse one candidate.

Ask the reviewer:

1. Which full-face result do you prefer: original, edited, or neither?
2. Do the liner tips, shadow edges and lip outline look naturally applied?
3. Does the result match the desired look, with recognizable unchanged features?

Keep an explicit reason for rejection. Only a user-preferred result that also
passes preservation checks may count as an improvement. Numeric visibility is
necessary for testing the edit, but is not a beauty score. Reference looks, if
supplied later, should guide makeup placement and finish rather than face shape.
