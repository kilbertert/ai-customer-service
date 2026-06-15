"""Dify-based backend package.

> **FROZEN-DEPRECATED 2026-06-15** — M10 G4 PR3 物理合并完成 (commits
> `475246c` + `fc7bc4a`)。本目录的 Dify 协议层代码已在 basjoo 仓
> `backend/services/dify/` 落地,新改动请在 basjoo 仓提交。本目录保留
> 作为 reference 镜像,只读不可改,等 M14 整体废弃时删除。
> 详见 `china_charge_kf/M10-FROZEN-README.md`。

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
