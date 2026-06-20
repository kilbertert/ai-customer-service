"""MiniMax 真实 API 探针 — 用可达的 api.minimax.chat 端点验证 model + JSON mode。"""
import json
import urllib.request
import urllib.error

API_KEY = "sk-cp-AkfjxjBodUHbdcu2ja48Aa2eHU05ubGfm1oWI2Y6B30p8an8ptj1Trq_cYzoO1twBIGsUapxjUtCLl7wJ8GobJ-biUzbbT_k_vrO3bHS1689QXwgFL9bo_E"
URL = "https://api.minimax.chat/v1/text/chatcompletion_v2"


def call(label: str, body: dict) -> None:
    print(f"\n=== {label} ===")
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"status: 200")
            print(f"content (first 300): {content[:300]}")
            print(f"usage: {data.get('usage')}")
            print(f"base_resp: {data.get('base_resp')}")
    except urllib.error.HTTPError as e:
        print(f"status: {e.code}")
        try:
            err = json.loads(e.read().decode("utf-8"))
            print(f"error: {json.dumps(err, ensure_ascii=False)[:500]}")
        except Exception:
            print(f"raw: {e.read()[:300]}")
    except Exception as e:
        print(f"exception: {type(e).__name__}: {e}")


# Probe 1: minimal call (model + messages)
call("probe1_minimal", {
    "model": "MiniMax-Text-01",
    "messages": [{"role": "user", "content": "Say 'ok' as JSON object with key status."}],
    "max_tokens": 100,
})

# Probe 2: with response_format=json_object (OpenAI-compat)
call("probe2_response_format", {
    "model": "MiniMax-Text-01",
    "messages": [{"role": "user", "content": "Return a JSON object: {\"status\":\"ok\"}"}],
    "response_format": {"type": "json_object"},
    "max_tokens": 100,
})

# Probe 3: with reply_constraints
call("probe3_reply_constraints", {
    "model": "MiniMax-Text-01",
    "messages": [{"role": "user", "content": "Return a JSON object: {\"status\":\"ok\"}"}],
    "reply_constraints": {"grep_constraint": "```json"},
    "max_tokens": 100,
})

# Probe 4: with system prompt forcing JSON (fallback)
call("probe4_system_prompt_json", {
    "model": "MiniMax-Text-01",
    "messages": [
        {"role": "system", "content": "You are a JSON generator. Output ONLY valid JSON. No prose, no markdown fences, no explanations."},
        {"role": "user", "content": "Return {\"status\":\"ok\"}"},
    ],
    "max_tokens": 100,
})