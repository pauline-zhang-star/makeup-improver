# Phase 1 evaluation record

Status: **local preflight tested on one supplied photo; Phase 2 prerequisites are not yet satisfied**.

Local smoke check: Python 3.9.6, MediaPipe 0.10.35, Apple Silicon. The official
Face Landmarker bundle loads and returns zero faces on a synthetic blank image.
One user-supplied 768 × 1024 photo passed exposure, blur and face-size checks:
one face and 478 landmarks. Mask overlays were inspected locally. This does not
validate occlusion detection or establish reliability across a test set.
The source was an MPO file with a JPEG extension; primary-image decoding is now
covered by a synthetic regression test. No source filenames or photo data are
recorded here.

The first explicitly user-authorized remote trial completed with GPT-4.1 mini
analysis and GPT Image 2 editing. It proposed one eyeshadow blend-upward change
and completed on the first image-edit attempt. Output dimensions were exactly
768 × 1024; pixels outside the mask were independently verified identical.
Maximum protected-landmark deviation was 0.00102049 in normalized coordinates.
Mean in-mask pixel delta was 20.5801. The user rejected the result: overall tone
looked washed out and the claimed eyeshadow improvement was not visible/useful.
Investigation confirmed that the source Display P3 ICC profile was discarded
without conversion. Numerical equality outside the mask only compared against
that already-incorrect working original; it did not establish color fidelity
to the source photo. The loader now converts to sRGB before stripping private
metadata and embeds the standard profile throughout export and comparison.
Regression tests cover profile conversion, output tags and metadata stripping.
A public-documentation provider assessment supports this consented experiment;
it is not individual written provider approval or public-release legal clearance.

Corrected trial 002: reprocessed the same input through its Display P3 profile
into sRGB. Independently verified the normalized original against the direct
ICC transform and verified matching sRGB profiles on both exported images.
Revised analysis reported no clear eyeshadow and uncertain eyeliner; it proposed
one lip-depth adjustment. One edit attempt completed, bringing the authorized
total to two image-edit calls. Pixels outside the lip mask were identical;
mean region delta was 14.7457 and protected-landmark deviation was 0.00185776.
Human acceptance remains pending. This result does not rehabilitate the original
eyeshadow claim or establish the planner's reliability across other photos.

Controlled blending trial 003: the user authorized one additional generation.
Reused the prior lip-depth plan without another analysis call. A full-strength
GPT Image 2 candidate was generated once and retained. Its maximum landmark
deviation was 0.00378243. Local blends at strengths 0.3, 0.5 and 0.7 all passed
the current numerical visibility band and before/after geometry checks; pixels
outside the lip mask were identical. Mean region deltas were 12.6660, 21.0976
and 29.5586 respectively. Maximum final landmark deviations were 0.0017740,
0.0017378 and 0.0025586. The comparison shows increasing lip-color depth with
matching full-face and lip crops. No strength is selected yet; these are not
calibrated findings across a test set or proof of identity preservation.

For each consented test image, record a non-identifying case label, model versions,
mask inspection, result status, attempts, runtime, cost and reviewer findings.
Keep photos and identifying records out of Git.

| Case | Mask accurate | Identity unchanged | Edit subtle and reproducible | Eye/lip realism | Outside pixels stable | No-change appropriate | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Local case 001 | Initial visual inspection only | Automated geometry check passed | User found no useful visible improvement | Not accepted | Pixel-identical to an incorrectly color-interpreted working original | Not evaluated | Rejected: color handling and visual usefulness |
| Local case 001, corrected trial 002 | Lip contour inspected | Automated geometry check passed | Lip-depth preview; user acceptance pending | User review pending | Pixel-identical outside lip mask; matching sRGB profiles | No eyeshadow suggested | Pending user review |

Required before proceeding:

Placement trial 004: the user confirmed all three changes were visible, then
rejected the overall aesthetic result as not looking better. The visible
eyeliner and lip-border edits are not accepted improvements. Revised planner
and renderer art direction is implemented but awaits a new visual trial; see
[the aesthetic review](ART_DIRECTION.md).

- Provider permission and mask capability documented for the specific model.
- Masks work reliably across the entire consented set, including occlusion rejection.
- Generated frame dimensions match the working original without a warp.
- Review confirms identity, geometry and skin texture preserved; no lighting/hair changes.
- Each suggested correction is visible and can be recreated with a small makeup touch-up.
- No visible edge seams or unsuitable pigment changes.
- Retry failures and no-changes cases behave correctly with real providers.

Crop optimization remains disabled. Public release also requires the design's
privacy/biometric review and an actual short-lived private storage implementation.
