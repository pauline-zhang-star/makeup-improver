# Image generation latency inspection — 2026-10-07

Same saved photo and Sophisticated technique plan, same exact region mask,
gpt-image-2, medium quality, 1152×1536 canvas. Two new sequential API edits:

| Output format | Method duration | API request duration | Image input tokens | Image output tokens |
| --- | ---: | ---: | ---: | ---: |
| PNG | 32.57 s | 32.361 s | 1,452 | 1,629 |
| JPEG (output_compression=100) | 32.25 s | 32.151 s | 1,452 | 1,629 |

Both passed the existing local preview geometry, preservation and selected-region
visible-change checks. No new AI comparison was requested. These local checks do
not establish semantic correctness or tutorial eligibility. The 0.32-second gap
in one trial is insufficient evidence to change the default PNG output.

Inspection findings:

- One image-edit request; n=1; no extra transport retries. Public workers allow
  at most one edit attempt. The mask does not reduce the requested canvas size.
- The full canvas is 1,769,472 pixels. The selected mask bounds are
  (295,564,882,1107). The request contained 2,581 text input tokens.
- Square region generation at native pixel resolution can use the context box
  (180,427,996,1243): 816×816, 665,856 pixels, 62.4% less output area. It does
  not downsample eyes, brows or skin pixels. This is a potential latency
  optimization, not a measured speedup until a real region edit is tested.
- The region is reinserted into an original-sized candidate before existing
  alignment, protected-pixel compositing, geometry and visible-change checks.
- A minimum 18%/48px context margin surrounds the selected mask. Cropping falls
  back to full-frame when a valid native-pixel region would not save at least
  20% of area, or when the source cannot satisfy the model minimum area.

Experimental settings:

- MAKEUP_EDIT_OUTPUT_FORMAT: png (default), jpeg, webp. JPEG/WebP use 100.
- MAKEUP_EDIT_CANVAS_MODE: full (default), region. No resolution quality change.

Generation usage records include requested dimensions, quality, output format,
encoded input-image bytes and decoded response-body byte count. These fields
contain no image data and help diagnose future real runs.

Official references:

- https://developers.openai.com/api/docs/guides/image-generation
- https://developers.openai.com/api/reference/resources/images/methods/edit

## Authorized native-resolution region trial

One additional same-input PNG/medium edit with an 816×816 native-resolution
canvas took 34.83 seconds end to end (34.698 seconds API request). It returned
an original-sized 1152×1536 candidate after reinsertion. Input image tokens
were 1,024 versus 1,452 for the full frame; output image tokens were 1,536
versus 1,629, only 5.7% fewer despite 62.4% fewer output pixels. The response
body was 1,571,960 bytes; encoded input images and mask totaled 995,219 bytes.
This sample did not improve latency. Variation between API calls prevents
attributing the difference to cropping alone. The default remains full/PNG.
No claim of proportional image-generation latency savings is supported here.

The region candidate passed the existing local preview checks (`preview_ready`).
No AI semantic review or tutorial call was made. This does not establish
visual accuracy across photos. The failed latency experiment is kept opt-in
for reproducible testing and is not enabled or deployed as an optimization.

## Low-quality default approved by user

The earlier synthetic lightly made-up test photo was generated in Work /
Polished style with gpt-image-2 quality=low, full canvas and PNG output.
Analysis took 17.507 seconds and generation 15.056 seconds. This photo and
style differ from the format/region trials, so this is not a controlled
medium-versus-low speed comparison. The result passed local preview checks;
no AI tutorial verification was requested. The user viewed a draggable
original/result comparison and approved low quality for all generation.

The provider default is now low, including the legacy edit path. Local web
and Vercel workers explicitly select low. Image dimensions, default full
canvas, PNG format and all quality gates are preserved. CLI-only overrides
remain available through MAKEUP_EDIT_QUALITY for future benchmarks.
