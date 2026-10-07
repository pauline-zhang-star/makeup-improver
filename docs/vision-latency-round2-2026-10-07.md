# Analysis and review latency, second pass — 2026-10-07

Four authorized gpt-4.1-mini requests used the same previously generated
Work / Polished low-quality photo pair. No image generation was requested.

| Stage | Previous transport | Experimental transport | Output tokens before/after |
| --- | ---: | ---: | ---: |
| Planning | 21.48 s | 5.83 s | 1,627 / 409 |
| Review | 9.77 s | 8.86 s | 593 / 511 |

The planning numbers are NOT a valid equivalent-work speed comparison.
The previous plan selected five techniques, but the experimental shortened
field names produced seven preserve decisions and zero proposals. Both
passed syntax and local gates, yet performed different amounts of output
work. The alias-based planning change was reverted, and is not deployed.

Review assessed all eight areas in both cases. For unchanged areas, the new
transport returns one observation rather than repeating identical before
and after text plus null instructions. Local decoding restores the normal
comparison contract; changed areas still require both observations and
bilingual instructions. Uncertain areas still retain both observations.

The reviewers differed on complexion: the previous response inferred a
smoother whole complexion and offered foundation advice; the new response
classified it unchanged. The generating plan contained only brows, liner,
shadow, blush and lips, with no foundation technique. This disagreement
needs visual evaluation; syntax validation alone does not establish quality.
One request per version cannot establish a stable 0.91-second speedup.

An available-model lookup confirmed gpt-5.6-luna is accessible to the existing
API project. Official model documentation supports image input, structured
output, Chat Completions and reasoning_effort=none. Any future comparison
will keep original planning fields, all numeric gates and full review images.
Testing this model requires additional authorized API calls; its production
selection is not assumed from documentation alone.

Sources:
- https://developers.openai.com/api/docs/guides/latency-optimization
- https://developers.openai.com/api/docs/models/gpt-5.6-luna

## Authorized faster-model comparison

Four further calls tested GPT-5.6 Luna with reasoning_effort=none on two
existing photo pairs, retaining the original planning field names.

| Photo | Analysis | Review | Selected analysis techniques | Review changed areas |
| --- | ---: | ---: | ---: | --- |
| Work / Polished fixture | 10.72 s | 9.11 s | 4 | eyebrows, eyeliner, lashes, eyeshadow, lips |
| Sophisticated saved pair | 10.62 s | 11.29 s | 5 | eyebrows, eyeliner, lashes, eyeshadow, lips |

Both plans had accepted proposals with no locally rejected proposals. They
are not identical to mini plans; deterministic style equivalence is not
claimed. All numeric, visibility, product-reduction and geometry constraints
remain in place. Two planning samples are preliminary evidence rather than
a broad accuracy evaluation or a latency guarantee.

Luna review failed to confirm blush in both pairs where mini had confirmed
it, and classified lashes changed. It was not consistently faster. Therefore
Luna is selected only for planning; review remains GPT-4.1 Mini, retaining
full photos, every matched crop, eight-area coverage and bilingual guidance.

The serving workers default analysis to gpt-5.6-luna and review to
gpt-4.1-mini. MAKEUP_PLANNING_MODEL and MAKEUP_REVIEW_MODEL allow independent
configuration. CLI --vision-model remains explicit. Reports retain the
planning visionModel when guidance is requested and record reviewModel
separately. API usage records contain each actual stage model. Rendering
remains gpt-image-2, quality=low, full frame and PNG.
