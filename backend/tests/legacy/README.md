# `tests/legacy/` — DEPRECATED

This directory holds test files from earlier milestone drafts (notably M4) whose
import paths no longer match the current basjoo backend layout.

## `test_main.py`

- **Origin**: M4 (FastAPI wiring test for `/health`, `/api/chat/stream` 4 错误路径,
  CORS preflight, `/api/files/upload`)
- **Status**: DEPRECATED, NOT collected by pytest
- **Why stale**:
  - Imports `services.dify.config` / `services.dify.main` — current layout is
    `backend/services/dify/` (package) + `backend/config.py` (settings) +
    `backend/main.py` (FastAPI app)
  - TestClient + respx SSE parser patterns in this file are now encoded in
    `tests/test_chat_stream_dify.py` and `tests/test_dify_client.py`
- **Migration path**: none. The M4 brief's coverage goals have been met by the
  current test suite (118+ Dify tests passing per M10+5 REPORT §4 D9 落点).

## How pytest skips this directory

`tests/legacy/conftest.py` sets `collect_ignore_glob = ["test_*.py"]`, which
prevents pytest from collecting any test file in this directory. The stale
file stays on disk for historical reference but never runs.

## Re-enable (not recommended)

If a future investigation genuinely needs the M4 scenarios:

1. Rewrite the imports to current basjoo layout
2. Add coverage to the modern test files instead — the legacy location
   should stay inert
3. Remove this `conftest.py` only as a last resort
