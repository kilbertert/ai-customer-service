from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class CozeError(RuntimeError):
    pass


@dataclass(frozen=True)
class CozeClient:
    api_base: str
    token: str

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def upload_file(self, *, filename: str, content: bytes, content_type: str | None) -> str:
        """
        Upload file to Coze and return file_id.
        Docs (may differ by region): POST {api_base}/v1/files/upload  multipart/form-data  field: file
        """
        url = f"{self.api_base.rstrip('/')}/v1/files/upload"
        files = {"file": (filename, content, content_type or "application/octet-stream")}

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(url, headers=self._headers(), files=files)

        if resp.status_code >= 400:
            raise CozeError(f"Upload failed: HTTP {resp.status_code} {resp.text}")

        data = resp.json()
        # 检查是否有错误码
        if data.get("code") != 0 and data.get("code") is not None:
            raise CozeError(f"Upload failed: {data}")
        file_id = (
            data.get("data", {}).get("id")
            or data.get("data", {}).get("file_id")
            or data.get("id")
            or data.get("file_id")
        )
        if not file_id:
            raise CozeError(f"Upload succeeded but file id missing: {data}")
        return str(file_id)

    async def run_workflow(self, *, workflow_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """
        Run Coze workflow and return raw json.
        Docs: POST {api_base}/v1/workflow/run  json: {workflow_id, parameters}
        """
        url = f"{self.api_base.rstrip('/')}/v1/workflow/run"
        payload = {"workflow_id": workflow_id, "parameters": parameters}

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload)

        if resp.status_code >= 400:
            raise CozeError(f"Workflow run failed: HTTP {resp.status_code} {resp.text}")
        return resp.json()

