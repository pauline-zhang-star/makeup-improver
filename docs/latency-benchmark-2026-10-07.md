# Latency optimization, 2026-10-07

One sequential, same-input comparison using the existing Sophisticated photo pair.
Vision model: gpt-4.1-mini for both versions. No image generation was requested.
Measured method duration includes image encoding and response validation.

| Stage | Before | Compact transport | Input tokens before/after | Output tokens before/after |
| --- | ---: | ---: | ---: | ---: |
| Planning | 21.72 s | 15.63 s | 10,069 / 7,927 | 1,553 / 1,314 |
| Observed changes and bilingual guidance | 16.78 s | 9.11 s | 12,871 / 10,089 | 1,036 / 567 |

Planning selected five techniques before and seven after; both passed the same local
validators. This is a latency comparison, not a deterministic plan-equivalence test.
Both reviewers assessed all eight areas and identified the same five changed areas:
eyebrows, eyeliner, eyeshadow, blush and lips. Neither reported preservation issues.
This single pair does not establish recall on subtle changes or accessory artifacts.
The existing rules, full photographs, every unique matched crop, and eight-area
coverage checks remain; broader visual validation is still needed.

An offline replay with saved candidate pixels reduced local pipeline processing
from 3.379 s to 1.140 s. The corner-connected flood fill was replaced by horizontal
NumPy runs. Equivalence tests cover random masks, enclosed holes and corner states.
This replay excludes upload, AI, process startup, serialization and network time.

The serving workers default MAKEUP_FAST_AI to 1. Setting it to 0 before server
startup restores the previous AI transport while keeping the equivalent local
mask optimization. Legacy CLI runs retain the previous AI contract unless enabled.

The 10-second planning / 5-second review targets were not reached in this trial.
No image-generation quality or model was changed. No fixed response-time guarantee
can be inferred from one API sample; provider queueing, caching and generated
output length vary. Compare a broader sample before selecting a faster model.
