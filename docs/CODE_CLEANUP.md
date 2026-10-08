# Deprecated-code cleanup — 2026-10-07

The supported implementation is the model-designed look pipeline, used by the Python CLI, local web server and Vercel backend. The native SwiftUI client calls the backend. Cleanup follows these entrypoints and their imports; shared image checks, masks, annotation rendering, API accounting and public-service guards remain supported.

Removed:

- Original three-region masked-edit pipeline, its provider methods, schemas, instruction templates and console entrypoint.
- Retired measurement-threshold and fixed-style recipe selector. The technique vocabulary, parameter limits and model-proposal validator remain.
- Offline blend sweeps, affine recomposition, Poisson lip blending and experiment commands that depended on those retired implementations.
- Tests for retired implementations and unused imports. Shared photo/landmark fixtures moved to `tests/flow_fixtures.py`; current-flow tests remain.
- Instructions advertising removed console commands. Historical design documents are marked as historical records.

Supported console commands: `makeup-refine` and `makeup-check`. The local server remains `python -m makeup_refine.web_app`.

Validation: 253 tests passed using `.venv-mp021/bin/python -m pytest -q`; CLI, photo-check and local-web `--help` entrypoints loaded with `PYTHONPATH=src`; `git diff --check` passed. No paid API calls were made. This validates local behavior and mocked integrations, not a new real-photo generation or production deployment.

Private photos, saved generation results and historical design records were retained. HEIF decoder imports are intentional registration side effects, not unused imports. Existing unrelated working-tree changes were preserved.
