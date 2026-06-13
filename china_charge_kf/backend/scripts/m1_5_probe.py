"""M1.5 协议探针:导入 v2 workflow yml + 跑 S1-S12 验收,落盘到 m1_5_findings/.

用法:
  cd china_charge_kf/backend
  python scripts/m1_5_probe.py

S1-S12 来自 docs/sse-event-mapping.md §8,v2-only 部分.
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


def parse_data_json(events: list[dict[str, str]]) -> list[dict]:
    out: list[dict] = []
    for e in events:
        raw = e.get("data") or ""
        if not raw.strip():
            continue
        try:
            out.append({"event_field": e.get("event"), "data": json.loads(raw)})
        except json.JSONDecodeError:
            out.append({"event_field": e.get("event"), "data_raw": raw[:300]})
    return out


async def import_v2_app(h: httpx.AsyncClient, api_base: str, auth: dict, yml_text: str) -> dict:
    """探测 /v1/* 是否有 app 导入端点.Dify 平台 /v1/ 是 service API,不暴露 app 创建/导入."""
    candidates = [
        (f"{api_base}/apps/import", "multipart"),
        (f"{api_base}/apps/import", "json"),
        (f"{api_base}/apps/imports", "multipart"),
    ]
    results: list[dict] = []
    for url, mode in candidates:
        try:
            if mode == "multipart":
                r = await h.post(
                    url,
                    headers=auth,
                    files={"yaml": ("workflow_v2.yml", yml_text.encode("utf-8"), "application/x-yaml")},
                    data={"mode": "workflow"},
                )
            else:
                r = await h.post(
                    url,
                    headers={**auth, "Content-Type": "application/json"},
                    json={"mode": "workflow", "yaml_content": yml_text},
                )
            results.append({
                "endpoint": url.replace(api_base, "<api>"),
                "mode": mode,
                "status": r.status_code,
                "body": (r.text[:800] if r.status_code >= 400 else (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:800])),
            })
        except Exception as e:
            results.append({
                "endpoint": url.replace(api_base, "<api>"),
                "mode": mode,
                "error": f"{type(e).__name__}: {e}",
            })
    return {"import_attempts": results}


async def probe_platform(h: httpx.AsyncClient, api_base: str, auth: dict) -> dict:
    """探测 Dify 平台能力,记录 v1 已知端点 + 找导入备选."""
    endpoints = [
        ("GET", f"{api_base}/info", None),
        ("GET", f"{api_base}/parameters", None),
        ("GET", f"{api_base}/apps", None),
        ("GET", f"{api_base}/workflows", None),
        ("GET", f"{api_base}/datasets", None),
    ]
    results: list[dict] = []
    for method, url, _ in endpoints:
        try:
            r = await h.request(method, url, headers=auth)
            ct = r.headers.get("content-type", "")
            body = r.json() if ct.startswith("application/json") else r.text[:400]
            results.append({
                "endpoint": url.replace(api_base, "<api>"),
                "method": method,
                "status": r.status_code,
                "body": body,
            })
        except Exception as e:
            results.append({"endpoint": url.replace(api_base, "<api>"), "method": method, "error": f"{type(e).__name__}: {e}"})
    return {"platform_probe": results}


async def main() -> None:
    here = Path(__file__).parent
    env = load_env(here.parent / ".env")

    import os
    env = {**env, **os.environ}

    api_base = env.get("DIFY_API_BASE", "").rstrip("/")
    api_key = env.get("DIFY_API_KEY", "")
    v2_api_key = env.get("DIFY_V2_API_KEY", "")  # v2 导入后由 Dify 平台签发的新 key
    end_user = env.get("DIFY_END_USER", "m15-probe")
    input_text_key = env.get("DIFY_INPUT_TEXT", "input_text")
    output_key = env.get("DIFY_OUTPUT_TEXT", "output")
    verify_ssl = env.get("DIFY_SSL_VERIFY", "true").lower() in ("true", "1", "yes")

    if not api_base or not api_key:
        print("ERR: DIFY_API_BASE / DIFY_API_KEY 缺失", file=sys.stderr)
        sys.exit(1)

    workflow_yml = (here.parent.parent / "Workflow-China_charge_seriver-draft-9380" / "workflow" / "workflow_v2.yml").read_text(encoding="utf-8")

    out_dir = here.parent / "m1_5_findings" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    findings: dict = {
        "_meta": {
            "ts": datetime.now().isoformat(),
            "api_base": api_base,
            "end_user": end_user,
            "v1_api_key_prefix": api_key[:8] + "..." if api_key else None,
            "v2_api_key_prefix": v2_api_key[:8] + "..." if v2_api_key else None,
            "verify_ssl": verify_ssl,
            "yml_bytes": len(workflow_yml),
        }
    }

    auth_v1 = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    json_headers_v1 = {**auth_v1, "Content-Type": "application/json"}
    auth_v2 = {"Authorization": f"Bearer {v2_api_key}"} if v2_api_key else {}
    json_headers_v2 = {**auth_v2, "Content-Type": "application/json"}

    print(f">>> SSL verify = {verify_ssl}")
    print(f">>> v2_api_key 提供: {bool(v2_api_key)}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0), verify=verify_ssl) as h:
        # 平台能力探测 (用 v1 key,只是看 endpoint 是否存在)
        if auth_v1:
            print(">>> 平台能力探测")
            findings["step0_platform"] = await probe_platform(h, api_base, auth_v1)

        # Step1 导入 v2 yml 探测 (已知 /v1/apps/import 不存在)
        if auth_v1:
            print(">>> Step1 探测 /v1/apps/import (预期 404)")
            findings["step1_import"] = await import_v2_app(h, api_base, auth_v1, workflow_yml)

        # 如果提供了 v2_api_key,直接跑 S1-S12 against v2
        if not v2_api_key:
            print(">>> 未提供 DIFY_V2_API_KEY. 需先在 Dify Web UI 导入 v2 yml 获得 v2 app API key.")
            print(">>> 步骤:登录 http://124.243.178.156:8501 → Studio → Import from DSL → 上传 workflow_v2.yml → 获得 API key → 写入 .env DIFY_V2_API_KEY=... → 重跑本探针")
            out_file = out_dir / "findings.json"
            out_file.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n>>> findings → {out_file}")
            return

        # ====== 用 v2 key 跑 S1: 纯文本问答 ======
        print(">>> S1 纯文本问答 (v2 key)")
        imported_app_id = "v2-key-direct"  # 用 v2 key 直接调用,无需 app_id
        try:
            r = await h.post(
                f"{api_base}/workflows/run",
                headers=json_headers_v2,
                json={
                    "inputs": {input_text_key: "你好,简单介绍一下你自己"},
                    "response_mode": "streaming",
                    "user": end_user,
                },
            )
            findings["S1_status"] = r.status_code
            body = b""
            async for chunk in r.aiter_bytes():
                body += chunk
            raw = body.decode("utf-8", errors="replace")
            findings["S1_raw_text_len"] = len(raw)
            findings["S1_raw_text"] = raw
            events = sse_parse(raw)
            findings["S1_event_count"] = len(events)
            findings["S1_event_types"] = [e.get("event") for e in events]
            parsed = parse_data_json(events)
            findings["S1_parsed_data"] = parsed
            selectors = []
            for p in parsed:
                d = p.get("data", {})
                if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
                    fv = d["data"].get("from_variable_selector")
                    if fv:
                        selectors.append({"event": d.get("event"), "selector": fv})
            findings["S1_selectors"] = selectors
            think_in_chunk = any(
                "<think>" in (p.get("data", {}).get("data", {}).get("text", "") or "")
                for p in parsed
                if p.get("data", {}).get("event") == "text_chunk"
            )
            findings["S1_think_in_text_chunk"] = think_in_chunk
            for p in parsed:
                if p.get("data", {}).get("event") == "workflow_finished":
                    inner = p["data"].get("data", {})
                    findings["S1_workflow_finished"] = {
                        "status": inner.get("status"),
                        "outputs_keys": list((inner.get("outputs") or {}).keys()),
                        "output_value_preview": str((inner.get("outputs") or {}).get(output_key, ""))[:200],
                        "total_tokens": inner.get("total_tokens"),
                        "elapsed_time": inner.get("elapsed_time"),
                    }
        except Exception as e:
            findings["S1_error"] = f"{type(e).__name__}: {e}"

        # S11: v2 单 LLM 链断言
        print(">>> S11 v2 单 LLM 链断言")
        non_2007_count = 0
        for sel in findings.get("S1_selectors", []):
            if sel.get("selector") and sel["selector"][0] != "2007":
                non_2007_count += 1
        findings["S11_text_chunk_count"] = len(findings.get("S1_selectors", []))
        findings["S11_non_2007_count"] = non_2007_count
        findings["S11_pass"] = (
            len(findings.get("S1_selectors", [])) > 0 and non_2007_count == 0
        )

        # S2: 文本+图片 (v2)
        if findings.get("S1_status") == 200:
            print(">>> S2 文本+图片 (v2)")
            try:
                png_1x1 = bytes.fromhex(
                    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
                    "0000000D49444154789C63F8CFC0000000020001E221BC330000000049454E44AE426082"
                )
                up = await h.post(
                    f"{api_base}/files/upload",
                    headers=auth_v2,
                    files={"file": ("probe.png", png_1x1, "image/png")},
                    data={"user": end_user},
                )
                if up.status_code in (200, 201):
                    file_id = up.json().get("id")
                    findings["S2_upload_file_id"] = file_id
                    r2 = await h.post(
                        f"{api_base}/workflows/run",
                        headers=json_headers_v2,
                        json={
                            "inputs": {
                                input_text_key: "请看这张图片,描述一下",
                                # yml now type: file-list (Array[File]), accepts file-ref array
                                "input_img_id": [{"type": "image", "transfer_method": "local_file", "upload_file_id": file_id}],
                            },
                            "response_mode": "blocking",
                            "user": end_user,
                        },
                    )
                    findings["S2_status"] = r2.status_code
                    try:
                        body2 = r2.json()
                        findings["S2_outputs_keys"] = list((body2.get("data", {}).get("outputs") or {}).keys())
                        findings["S2_output_preview"] = str((body2.get("data", {}).get("outputs") or {}).get(output_key, ""))[:200]
                        findings["S2_status_data"] = body2.get("data", {}).get("status")
                        findings["S2_error"] = body2.get("data", {}).get("error")
                    except Exception:
                        findings["S2_body_text"] = r2.text[:600]
                else:
                    findings["S2_upload_status"] = up.status_code
            except Exception as e:
                findings["S2_error"] = f"{type(e).__name__}: {e}"

        # S4: Dify 401 (用错 key 跑 v1 路径验证)
        print(">>> S4 错误 API key")
        try:
            r = await h.post(
                f"{api_base}/workflows/run",
                headers={**json_headers_v1, "Authorization": "Bearer app-INVALID-KEY-XXXXXXXX"},
                json={"inputs": {}, "response_mode": "blocking", "user": end_user},
            )
            findings["S4_status"] = r.status_code
            findings["S4_body"] = r.text[:600]
        except Exception as e:
            findings["S4_error"] = f"{type(e).__name__}: {e}"

        # S6: workflow 内部失败 (假 file_id)
        if findings.get("S1_status") == 200:
            print(">>> S6 假 file_id 触发失败")
            try:
                r = await h.post(
                    f"{api_base}/workflows/run",
                    headers=json_headers_v2,
                    json={
                        "inputs": {
                            input_text_key: "test",
                            "input_img_id": [{"type": "image", "transfer_method": "local_file", "upload_file_id": "00000000-0000-0000-0000-000000000000"}],
                        },
                        "response_mode": "blocking",
                        "user": end_user,
                    },
                )
                findings["S6_status"] = r.status_code
                try:
                    body6 = r.json()
                    findings["S6_data_status"] = body6.get("data", {}).get("status")
                    findings["S6_outputs_keys"] = list((body6.get("data", {}).get("outputs") or {}).keys())
                    findings["S6_error_field"] = body6.get("data", {}).get("error")
                except Exception:
                    findings["S6_body_text"] = r.text[:600]
                # v2 captures the platform-layer rejection directly
                try:
                    findings["S6_response_body"] = r.json()
                except Exception:
                    findings["S6_response_body"] = r.text[:600]
                # S6b: workflow-internal failure (real file the LLM rejects)
                # This is the v1 "S6" behavior — in v2, a fake file_id is caught at the platform layer (S6 above),
                # so to reach workflow-failed we need a real file the LLM rejects (e.g., 1x1 PNG too small).
                png_1x1 = bytes.fromhex(
                    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
                    "0000000D49444154789C63F8CFC0000000020001E221BC330000000049454E44AE426082"
                )
                up6 = await h.post(
                    f"{api_base}/files/upload",
                    headers=auth_v2,
                    files={"file": ("probe6b.png", png_1x1, "image/png")},
                    data={"user": end_user},
                )
                if up6.status_code in (200, 201):
                    fid6 = up6.json().get("id")
                    findings["S6b_upload_file_id"] = fid6
                    r6b = await h.post(
                        f"{api_base}/workflows/run",
                        headers=json_headers_v2,
                        json={
                            "inputs": {
                                input_text_key: "test workflow-failed path",
                                "input_img_id": [{"type": "image", "transfer_method": "local_file", "upload_file_id": fid6}],
                            },
                            "response_mode": "blocking",
                            "user": end_user,
                        },
                    )
                    findings["S6b_status"] = r6b.status_code
                    try:
                        body6b = r6b.json()
                        findings["S6b_data_status"] = body6b.get("data", {}).get("status")
                        findings["S6b_error"] = body6b.get("data", {}).get("error")
                    except Exception:
                        findings["S6b_body_text"] = r6b.text[:600]
            except Exception as e:
                findings["S6_error"] = f"{type(e).__name__}: {e}"

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
        elif isinstance(v, dict) and len(v) > 6:
            v = {kk: (str(vv)[:100] if not isinstance(vv, (int, float, bool, type(None))) else vv) for kk, vv in list(v.items())[:6]}
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
