"""M0.5 协议探针:验证 v1 边界外的 4 类调用,落盘到 m0_5_findings/.

用法:
  cd china_charge_kf/backend
  python scripts/m0_5_probe.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx


def load_env(env_path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def sse_parse(raw: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            if current:
                events.append(current)
                current = {}
            continue
        if ":" in line:
            field, _, value = line.partition(":")
            current[field.strip()] = value.lstrip()
    if current:
        events.append(current)
    return events


async def main() -> None:
    here = Path(__file__).parent
    env = load_env(here.parent / ".env")

    import os
    env = {**env, **os.environ}  # shell 覆盖 .env

    api_base = env.get("DIFY_API_BASE", "").rstrip("/")
    api_key = env.get("DIFY_API_KEY", "")
    end_user = env.get("DIFY_END_USER", "m05-probe")
    input_text_key = env.get("DIFY_INPUT_TEXT", "input_text")
    output_key = env.get("DIFY_OUTPUT_TEXT", "output")
    verify_ssl = env.get("DIFY_SSL_VERIFY", "true").lower() in ("true", "1", "yes")

    if not api_base or not api_key:
        print("ERR: DIFY_API_BASE / DIFY_API_KEY 缺失", file=sys.stderr)
        sys.exit(1)

    out_dir = here.parent / "m0_5_findings" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    findings: dict = {
        "_meta": {
            "ts": datetime.now().isoformat(),
            "api_base": api_base,
            "end_user": end_user,
            "api_key_prefix": api_key[:8] + "...",
            "input_text_key": input_text_key,
            "output_key": output_key,
            "verify_ssl": verify_ssl,
        }
    }

    auth = {"Authorization": f"Bearer {api_key}"}
    json_headers = {**auth, "Content-Type": "application/json"}

    print(f">>> SSL verify = {verify_ssl}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), verify=verify_ssl) as h:
        # V2: 文件上传
        print(">>> V2 文件上传")
        png_1x1 = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
            "0000000D49444154789C63F8CFC0000000020001E221BC330000000049454E44AE426082"
        )
        try:
            r = await h.post(
                f"{api_base}/files/upload",
                headers=auth,
                files={"file": ("probe.png", png_1x1, "image/png")},
                data={"user": end_user},
            )
            findings["V2_upload_status"] = r.status_code
            findings["V2_upload_content_type"] = r.headers.get("content-type")
            try:
                findings["V2_upload_body"] = r.json()
            except Exception:
                findings["V2_upload_body"] = r.text[:1000]
        except Exception as e:
            findings["V2_upload_error"] = f"{type(e).__name__}: {e}"

        # V9: 流式调用
        print(">>> V9 流式调用")
        try:
            r = await h.post(
                f"{api_base}/workflows/run",
                headers=json_headers,
                json={
                    "inputs": {input_text_key: "你好"},
                    "response_mode": "streaming",
                    "user": end_user,
                },
            )
            findings["V9_streaming_status"] = r.status_code
            findings["V9_streaming_content_type"] = r.headers.get("content-type")
            body = b""
            async for chunk in r.aiter_bytes():
                body += chunk
            raw_text = body.decode("utf-8", errors="replace")
            findings["V9_streaming_raw_bytes_len"] = len(body)
            findings["V9_streaming_raw_text"] = raw_text
            sse_events = sse_parse(raw_text)
            findings["V9_streaming_event_count"] = len(sse_events)
            findings["V9_streaming_event_types"] = [e.get("event") for e in sse_events]
            findings["V9_streaming_event_samples"] = [
                {"event": e.get("event"), "data_preview": (e.get("data") or "")[:600]}
                for e in sse_events[:12]
            ]
        except Exception as e:
            findings["V9_streaming_error"] = f"{type(e).__name__}: {e}"

        # V10a: 错误 API key
        print(">>> V10a 错误 key")
        try:
            r = await h.post(
                f"{api_base}/workflows/run",
                headers={**json_headers, "Authorization": "Bearer app-INVALID-KEY-XXXXXXXX"},
                json={"inputs": {}, "response_mode": "blocking", "user": end_user},
            )
            findings["V10a_bad_key_status"] = r.status_code
            findings["V10a_bad_key_body"] = r.text[:1000]
        except Exception as e:
            findings["V10a_bad_key_error"] = f"{type(e).__name__}: {e}"

        # V10b: workflow 内部错误(假 file_id 触发 KB 节点找不到文件)
        print(">>> V10b workflow 内部错误")
        try:
            r = await h.post(
                f"{api_base}/workflows/run",
                headers=json_headers,
                json={
                    "inputs": {
                        input_text_key: "test",
                        "input_img_id": [{
                            "type": "image",
                            "transfer_method": "local_file",
                            "upload_file_id": "00000000-0000-0000-0000-000000000000",
                        }],
                    },
                    "response_mode": "blocking",
                    "user": end_user,
                },
            )
            findings["V10b_workflow_fail_status"] = r.status_code
            findings["V10b_workflow_fail_content_type"] = r.headers.get("content-type")
            try:
                findings["V10b_workflow_fail_body"] = r.json()
            except Exception:
                findings["V10b_workflow_fail_body"] = r.text[:2000]
        except Exception as e:
            findings["V10b_workflow_fail_error"] = f"{type(e).__name__}: {e}"

    out_file = out_dir / "findings.json"
    out_file.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n>>> findings → {out_file}\n")
    print("=== 摘要 ===")
    for k, v in findings.items():
        if k.startswith("_"):
            continue
        if isinstance(v, str) and len(v) > 200:
            v = v[:200] + f"... ({len(v)} chars total)"
        elif isinstance(v, list) and len(v) > 3:
            v = v[:3] + [f"... +{len(v) - 3} more"]
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
