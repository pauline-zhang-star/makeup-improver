# Offline photo and lip regression checks

Run all checks from the project root:

```sh
.venv-mp021/bin/python -m pytest -q
```

`tests/test_lip_regression.py` always runs without photos or API access. It covers three skin-color fixtures, closed/slightly parted/open/teeth-visible mouths, and straight/rolled landmarks (24 cases). It checks lip contact coverage, exact preservation of oral-interior pixels and pixels outside the edit mask. The review contract is checked in both standard and fast transport modes.

`tests/test_private_photo_regressions.py` reads the optional, Git-ignored `private-fixtures/photo-regression/manifest.json`. The current local set has four saved photographs: deep-, medium- and light-skin closed-mouth cases and a light-skin open-mouth case. Image checksums pin the input files; saved landmarks avoid detector/model setup during test runs. These tests exercise masks and compositing with conspicuous synthetic pigment, not new AI generation. Photographs and landmarks must stay private. Without the manifest this optional suite is skipped; the procedural suite still runs.

The comparison prompt now requires inspection of the final lip seam. A new gray/bare band is a makeup artifact; a natural thin crease, actual oral cavity and normal highlights are different. Mouth-state and teeth-visibility preservation remain mandatory. AI review compliance and full generation quality require separate visual trials; mocked contract tests cannot establish those qualities.

The 4% landmark gap/width cutoff is a heuristic, not a calibrated universal mouth-state detector. Very narrow openings and difficult poses still need visual review. The current photographic set does not yet contain a real teeth-visible photograph; teeth preservation is covered procedurally. Expand the private set when such test photographs become available.
