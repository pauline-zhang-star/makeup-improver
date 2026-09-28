# Revised image-first flow

> Historical implementation note: the current pipeline selects up to seven
> measured techniques before the image edit, then accepts or rejects the API
> image directly. The alignment and local compositing below describe the older
> experiment. See [the README](../README.md) and
> [technique mapping table](technique-mapping-table.md) for the active flow.

The active flow additionally allows optional facial base makeup in both Auto and
selected styles. Facial skin need not remain pixel-identical: realistic coverage,
tone evenness and finish changes are permitted and explained only when observed.
This does not authorize changes to identity, geometry, hair, glasses, clothes,
background or scene lighting. There is no local cosmetic blending in this path.

This revision implements the user's updated flow in the existing Python repository.
Inspection found no Xcode project, Swift source, React Native/Expo package, mobile UI,
backend or database. The user confirmed that the change should apply to this repo.
No mobile app or new server has been scaffolded.

## Files changed

| File | Change |
| --- | --- |
| `src/makeup_refine/cli.py` | Default image-first command, saved image pair and comparison-only retry |
| `src/makeup_refine/legacy_cli.py` | Preserved previous command |
| `src/makeup_refine/look_models.py` | Eight styles and eight-area observed-step contract |
| `src/makeup_refine/look_prompts.py` | Direct generation brief and separate visual-comparison prompt |
| `src/makeup_refine/look_pipeline.py` | Generate, align, composite, validate, save, then explain |
| `src/makeup_refine/look_mask.py` | Face-anchored cosmetic regions with protected eye and mouth interiors |
| `src/makeup_refine/look_alignment.py` | Bounded affine correction for whole-face translation and scale |
| `src/makeup_refine/look_composite.py` | Complexion tone transfer and legacy lip-compositing helpers |
| `src/makeup_refine/lip_blend.py` | Candidate lip contour preservation, automatic Poisson boundary repair and artifact checks |
| `src/makeup_refine/recompose_cli.py` | Offline replay of saved candidates through the production compositor, without API calls |
| `src/makeup_refine/look_view.py` | Render observed instructions and incomplete/error states |
| `src/makeup_refine/providers.py` | Real direct-edit and paired-image comparison methods |
| `src/makeup_refine/interfaces.py` | Independent editor and explainer protocols |
| `src/makeup_refine/preflight.py` | Reuse face checks without requiring legacy masks |
| `src/makeup_refine/report.py` | Draggable two-image comparison and new instruction view |
| `tests/test_look_flow.py` | Flow, provider, storage, retry and report tests |
| `pyproject.toml` | New description and preserved legacy CLI entry point |
| `README.md` | Current setup, commands, outputs and limitations |
| `docs/DESIGN.md` | Link to the revised behavior while retaining historical design |
| `docs/IMAGE_FIRST_FLOW.md` | Architecture, file inventory, limitations and remaining work |

## Architecture

`cli.py` loads and normalizes the selfie, accepts an optional style (default Auto),
and calls `LookPipeline`. Preflight uses the existing face, exposure and sharpness
checks without trying to classify whether makeup is present.

1. `LookEditor.enhance(original, style, mask)` makes one direct image-edit request.
   Its brief preserves the person and scene and asks the model to improve existing
   makeup where appropriate. It does not receive an advice plan, prior generated
   image or half-face collage. A cosmetic-region mask guides the model. Small
   photos are proportionally enlarged to valid API dimensions without padding.
2. Local landmarks check whether the returned full-frame candidate has a coherent
   scale/translation error. A bounded affine transform corrects that error; a
   non-affine change is rejected. The corrected candidate is composited through
   the cosmetic mask onto the original pixels, with a bounded low-frequency complexion
   transfer for selected styles. Original and candidate lip contours determine a local
   blend region. A harmonic color correction retains the generated fuller contour and
   lip texture while matching surrounding skin. Three margins are scored for outer
   boundary jumps, skin patches and lip-detail retention. Unsafe mouth changes or
   failed seam checks reject the image; there is no original-shape fallback. The resulting final image
   must pass the existing landmark check and is saved before explanation.
3. `LookExplainer.explain_changes(original, enhanced)` receives the two images in
   that order. It receives neither the style brief nor a makeup plan, so it must
   describe the images rather than echo intended changes.
4. `LookComparison` requires all eight areas exactly once, each explicitly marked
   changed, unchanged or uncertain, with before/after evidence and confidence.
   Missing/duplicate areas fail validation rather than silently dropping a feature.
   Only changed areas may have a practical application instruction. Only changed
   areas with confidence at least 0.8 are displayed. This is a provisional filter,
   not proof of visual accuracy. Uncertain areas and empty results get no fallback
   advice. The complete assessments are saved for inspection; numbered steps and
   arrows share the filtered list. This guarantees coverage, not perfect visual
   judgment, and never forces a lip change. Visible non-makeup preservation issues reject the result.
5. The existing offline HTML report shows separate original/enhanced image layers
   under a pointer-draggable divider, with a keyboard-accessible range control.
   Observed instructions appear under “How to Achieve This Look.” It never saves
   or requests a half-face comparison image.

`LookPipeline.recompose` and `makeup-recompose` replay steps 2 and 5 locally from
saved images, without invoking either provider. Stale guidance is cleared. The lip
checks are heuristics: RGB boundary-gradient P95 <= 12, surrounding-skin delta P95
<= 20 and smoothed local chromatic-difference peak <= 36, relative lip-gradient error <= 0.45, and full
coverage of the generated contour. Solver convergence is required. These constants
and the lip-area ratio guard (0.65–1.6) need broader calibration. The checks detect
compositing artifacts, not whether a makeup style is aesthetically flattering.

The After layer also contains presentation-only numbered badges and arrows.
Badges sit beside the face; landmark anchors point at the relevant makeup areas.
Their numbering is derived from the displayed steps in the same order. The entire
After layer (photo and callouts together) is clipped by the slider, so Original
never receives annotations. Fixed-size high-contrast badges stay legible on narrow
screens. Neither source PNG is modified. Anchors are approximate area pointers,
not exact makeup application boundaries; future results use the validated source
landmarks and the existing preview was positioned locally on its enhanced image.

`originalImage` and `enhancedImage` in `result.json` refer to local PNG files in a
private output directory. The original means the orientation-normalized, metadata-
stripped, color-managed working selfie, currently downscaled to a 1024-pixel edge.
Original camera bytes are not overwritten. Files remain until explicitly deleted.

States include `enhanced_ready`, `completed`, `completed_no_visible_changes`,
`instructions_unavailable`, `rejected`, and `failed`. A saved enhanced image survives
explanation failure. `--retry-instructions` compares the same saved pair and cannot
call generation. Rejected images remain local for diagnosis but are not presented
as an accepted result. An identical pair has no steps and needs no paid comparison.

The old `Pipeline`, three-area models, masks, compositing, guides, offline sweeps and
experiments remain intact. `makeup-refine-legacy` / `python -m makeup_refine.legacy_cli`
retain the previous CLI. The default `makeup-refine` command now uses this revision.
Shared provider transport, imaging and reporting are reused rather than rebuilt.

## Style configuration

Auto, Natural, Work / Polished, Korean Soft, Fresh, Date Night, Sophisticated and
Soft Glam are all available. Style selection is a single optional argument now;
a future mobile adapter can present the same enum as optional chips without a
questionnaire. Auto asks the image model to choose from the selfie in that same
generation call. Suitability is an AI judgment, not a validated aesthetic score.
Style briefs are explicit hand-written prompt configuration, not learned user taste.
Auto uses the current conservative cosmetic mask; every explicitly selected style
expands its feature widths by a provisional factor of 1.25. In the saved 788 × 524
test portrait, this raises mask coverage from 0.0791 to 0.0985 and lip-region
coverage from 0.0098 to 0.0117. Eye and mouth interiors remain excluded. Fixed
circular nostril cutouts were removed after they produced dark nose-side spots. Wider
coverage alone has not been shown to improve aesthetic quality; no paid style-
selected generation has yet tested this setting.

## Validation and remaining work

- Tests exercise call order, Auto and all named styles, the exact image pair sent
  for comparison, all eight areas, omission of uncertain/unchanged steps, empty
  results, preservation rejection, local file storage and comparison-only retry.
  Test providers and HTTP responses are mocked. The runtime provider is real.
- The latest Auto test reuses `IMG_1202.JPG` and saves the selected four-area
  candidate in `outputs/img1202-four-area-011`. Local-only cheek/eye blending
  revision `outputs/img1202-four-area-014` is the reviewed result. The comparison
  identified eyeliner, eyeshadow, blush, and a lower-lip center highlight; these
  four planned areas are shown as steps. It also claimed eyebrow, lash, and
  complexion changes that were not separately planned, so those claims remain
  in diagnostics rather than the user guide. Eyeliner and lip highlight are
  easiest to see; blush and eyeshadow remain subtle. This meets the provisional
  step-count goal according to the comparator, but does not establish that the
  result is aesthetically better or that all four changes are obvious to a user.
- Auto trial 005 used the previously supplied consented photo for one image-edit
  request and one paired-image comparison. Dimensions and the landmark guard
  passed (maximum deviation 0.002898). The comparison returned six steps and no
  preservation flags. Human inspection found visible makeup changes and smoother
  skin, and an apparent lip-color change missing from the guide. User preference
  and instruction completeness remain unvalidated. Validate full-face quality,
  glasses/hair/background preservation and faithfulness of instructions on consented
  photos before accepting it. The prior user's aesthetic rejection still stands.
- On the 788 × 524 portrait, the earlier padded full-frame candidate zoomed the
  face about 1.2× and failed the geometry gate at 0.111. A later real API edit
  using proportional scaling and a cosmetic mask reduced raw drift to 0.0185,
  but the model opened the mouth and the initial masked result still failed.
  Reprocessing that saved candidate with original-mouth lip-color transfer and
  softer blush gave a 0.00572 final landmark deviation, below the 0.012 gate.
  The pair and slider are saved in `outputs/auto-look-009-final-diagnostic`.
  Its instructions are unavailable: the separate comparison upload was blocked
  by automatic approval review pending explicit user authorization. This is a
  local recovery of one candidate, not a fresh end-to-end test of all latest code.
- Following visual feedback that the result mostly deepened eye and lip color,
  Auto now asks for soft everyday polish through cosmetic placement: brow shape,
  apparent eye shape, nose bridge/alar contour, and lip pigment outline. The
  original mouth opening and eye interiors remain protected;
  the eye composite is locally feathered to avoid a hard boundary.
  `nose_contour` is an eighth comparison/annotation area. Local mask inspection
  and automated tests pass.
- A later enlarged eye/lip mask test generated one new candidate. The generated
  mouth remained closed and its lip landmarks deviated at most 0.00459, allowing
  the spatial lip detail to be kept. The final image passed the geometry gate at
  0.00637 and is saved in `outputs/auto-look-011-expanded-spatial`. The separate
  image-comparison request was blocked by automatic approval review, so this
  test has no generated steps or validated aesthetics.
- A consented Korean Soft test on a new portrait ran the full image and text
  flow. The 472 × 1024 working image used the selected-style mask (coverage
  0.14166); its generated final passed the landmark gate at 0.00561. Human
  inspection found an oval eye-region blending seam, despite the comparison
  reporting no preservation issue. Reprocessing the same saved candidate with
  broader inward eye feathering reduced that seam without another image edit;
  the repaired final passed at 0.00565 and was compared again. The comparison
  returned seven changed steps and classified nose contour unchanged. Manual
  review found overconfident lip-finish and whole-face complexion instructions,
  so the saved steps require human correction. The comparator prompt was
  tightened, but an additional paid retry was blocked by automatic approval
  review. No claim of accepted aesthetic quality or instruction accuracy is made.
- The provider mask alone has no exact outside-mask preservation guarantee; local
  compositing now enforces pixel equality outside allowed cosmetic regions. Face
  landmarks do not verify identity, glasses or the entire scene; vision-model
  preservation checks are also fallible. Review both images manually.
- GPT Image 2 requests proportionally enlarge the entire frame to meet its
  multiples-of-16 and minimum-pixel constraints. Returned candidates are reduced
  to the working original size before alignment and localized compositing. Both
  saved photos retain the same working dimensions. An unexpected provider canvas
  size is rejected. Unusual aspect ratios still need real-provider testing.
  HEIC input is still unsupported in the Python loader.
- There is no iOS upload picker, optional style UI or native slider to change in this
  checkout. A future app can consume the style/result contracts through an adapter;
  the image service and explanation service remain independent of UI platforms.
- Credential delivery for a distributed mobile build is unresolved. The local
  prototype reads `.env`; do not embed the developer's API key in a shipped app.
  No server, accounts, database, fake upload endpoint or mobile networking mock was
  added to make the prototype appear to be an iOS app.
- Defaults remain configured in code: style briefs, medium image quality, the
  0.8 comparison-confidence threshold and the existing 0.012 landmark threshold.
  Model names are CLI configuration, not hardcoded model upgrades.

API contracts were checked against the official [image generation guide](https://developers.openai.com/api/docs/guides/image-generation)
and [multiple-image vision input guide](https://developers.openai.com/api/docs/guides/images-vision).
