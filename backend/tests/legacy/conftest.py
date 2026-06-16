"""DEPRECATED legacy test directory — pytest collection guard.

``test_main.py`` in this directory imports paths from the M4 era
(``services.dify.config`` / ``services.dify.main``) that no longer exist
in the current basjoo backend (now ``backend/services/dify/`` package +
``backend/config.py``). The coverage it attempted has been superseded by:

- ``tests/test_chat_stream_dify.py``  (SSE happy / error paths)
- ``tests/test_dify_client.py``        (DifyClient unit)
- ``tests/test_dify_admin_client.py``  (DifyAdminClient + D9 patches)

This ``conftest.py`` blocks pytest from collecting any ``test_*.py`` here
so the stale file does not produce import errors at collection time.
"""
from __future__ import annotations

collect_ignore_glob = ["test_*.py"]
