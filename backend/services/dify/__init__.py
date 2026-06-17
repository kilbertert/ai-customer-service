"""Dify-based backend package.

This package is a drop-in alternative to the original Coze-based backend
(``app/``). It exposes the same ``/api/chat`` contract so the frontend can
flip between the two backends by changing ``VITE_API_BASE``.

Key Dify differences vs Coze:
- File upload: ``POST {api_base}/files/upload`` (multipart, requires ``user``)
  returns ``id`` (UUID) which is the ``upload_file_id``.
- Workflow exec: ``POST {api_base}/workflows/run`` (JSON, requires ``inputs``
  + ``user``). For file-type workflow inputs, pass a list of file objects:
  ``[{"type": "image", "transfer_method": "local_file", "upload_file_id": "..."}]``.
- Workflow result is at ``data.outputs.<var_name>``.
- HTTP 200 is returned even on workflow failure — check ``data.status``.
"""

__all__ = ["main"]
