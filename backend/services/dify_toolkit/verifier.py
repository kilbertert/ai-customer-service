"""End-to-end verifier for deployed Dify workflows (P0-C PR 2)。

C1 安全收敛 (D8): 干掉 ``SSHClient`` + curl over SSH,改 basjoo-side httpx 直调
``POST {dify_api_base}/v1/chat-messages``(走 tenant 凭据,不调 SSH)。

用法:
    from services.dify_toolkit import TestCase, Verifier
    v = Verifier.from_workspace(workspace, api_key=agent.dify_api_key)
    report = await v.run([
        TestCase(case_id="leg_pain", text="我腿疼",
                 expected={"scene": "symptom"}),
    ])
    print(report)  # VerificationReport 1/1 passed (100%)

设计取舍:
  - 只保留 live HTTP test 路径(老 toolkit 的 inline-code-test 路径在 builder
    单测里覆盖 — ``backend/tests/test_dify_toolkit_builder.py::test_yaml_round_trip``)。
  - 凭据从 ``Workspace.dify_api_base`` + ``Agent.dify_api_key`` 拿(后者从
    ``DifyAdminClient.enable_api_and_create_key()`` 在 provisioning 时拿到后存 DB)。
  - 单 case timeout = 30s(LLM 调用 + Dify 内部分发);整批 = 30s × N(串行)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from models import Workspace

from .constants import DIFY_CHAT_MESSAGES_PATH

logger = logging.getLogger(__name__)


# Single-case + per-request timeout. 30s covers LLM round-trip + Dify internal dispatch.
DEFAULT_TIMEOUT_SECONDS: float = 30.0


@dataclass
class TestCase:
    """Single end-to-end test case for a deployed Dify workflow.

    Attributes:
        case_id:     short id used in test output
        text:        user text input (may be empty)
        expected:    dict of expected output fields. ``>=0.7`` strings = numeric
                     comparison (e.g. ``{"confidence": ">=0.7"}``). Other keys
                     use deep equality. Keys starting with ``_`` are ignored
                     (so you can stash debug fields).
        user_id:     optional ``user`` field for Dify chat API (tracking)
        description: human-readable description printed in failures
    """

    case_id: str
    expected: dict[str, Any]
    text: str = ""
    user_id: str = ""
    description: str = ""


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    actual: dict[str, Any]
    expected: dict[str, Any]
    mismatches: list[str] = field(default_factory=list)
    description: str = ""
    error: str | None = None


@dataclass
class VerificationReport:
    total: int
    passed: int
    failed: int
    results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    def __str__(self) -> str:
        return (
            f"VerificationReport {self.passed}/{self.total} passed "
            f"({self.pass_rate:.0%})"
        )


class Verifier:
    """Live HTTP verifier for a deployed Dify workflow.

    凭据: ``dify_api_base``(workspace 级) + ``api_key``(Agent.dify_api_key,
    provisioning 时拿)。无 SSH、无 docker、无凭据 env。
    """

    def __init__(
        self,
        *,
        dify_api_base: str,
        api_key: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not dify_api_base:
            raise ValueError("dify_api_base is required (Workspace.dify_api_base)")
        if not api_key:
            raise ValueError(
                "api_key is required (Agent.dify_api_key, "
                "provisioned by DifyAdminClient.enable_api_and_create_key)"
            )
        self.dify_api_base = dify_api_base.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_workspace(
        cls,
        workspace: Workspace,
        *,
        api_key: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> "Verifier":
        """C3 决策: 从 workspace + agent 拿凭据,per-tenant 隔离。"""
        dify_api_base = getattr(workspace, "dify_api_base", "") or ""
        return cls(
            dify_api_base=dify_api_base,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    async def run(self, cases: list[TestCase]) -> VerificationReport:
        """串行跑全部 cases,返回汇总报告。

        串行(非并发)原因:
          - Dify workflow run 是 CPU + LLM 调用,单 Dify 实例并发跑 N 个会
            互相竞争 worker,串行更稳。
          - 测试 case 数小(典型 <20),延迟可接受。
        """
        results: list[CaseResult] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for case in cases:
                results.append(await self._run_one(client, case))
        passed = sum(1 for r in results if r.passed)
        return VerificationReport(
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            results=results,
        )

    async def _run_one(
        self,
        client: httpx.AsyncClient,
        case: TestCase,
    ) -> CaseResult:
        url = f"{self.dify_api_base}{DIFY_CHAT_MESSAGES_PATH}"
        # Dify /v1/chat-messages 用 form-encoded inputs (query: str, user: str)
        # 返回 mode=blocking 的 JSON: {"answer": "...", "conversation_id": "...", ...}
        payload = {
            "inputs": {},
            "query": case.text,
            "response_mode": "blocking",
            "user": case.user_id or f"verifier-{case.case_id}",
            "conversation_id": "",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            return CaseResult(
                case_id=case.case_id,
                passed=False,
                actual={},
                expected=case.expected,
                mismatches=[f"timeout: {e}"],
                description=case.description,
                error=f"timeout after {self.timeout_seconds}s",
            )
        except httpx.HTTPError as e:
            return CaseResult(
                case_id=case.case_id,
                passed=False,
                actual={},
                expected=case.expected,
                mismatches=[f"http error: {e}"],
                description=case.description,
                error=str(e),
            )

        if resp.status_code >= 400:
            return CaseResult(
                case_id=case.case_id,
                passed=False,
                actual={"status_code": resp.status_code, "body": resp.text[:500]},
                expected=case.expected,
                mismatches=[f"http {resp.status_code}: {resp.text[:200]}"],
                description=case.description,
                error=f"http {resp.status_code}",
            )

        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return CaseResult(
                case_id=case.case_id,
                passed=False,
                actual={"raw": resp.text[:500]},
                expected=case.expected,
                mismatches=[f"json parse: {e}"],
                description=case.description,
                error=f"json parse: {e}",
            )

        # Dify chat response: {"answer": "<text>", "conversation_id": "...", ...}
        # 把 answer 字符串当 single-field result 解析;若 answer 是 JSON dict,
        # 也兼容(部分 CodeNode 节点直接返回 JSON)。
        actual = _parse_dify_answer(data.get("answer", ""))
        actual.setdefault("_conversation_id", data.get("conversation_id", ""))

        mismatches = _compare(actual, case.expected)
        return CaseResult(
            case_id=case.case_id,
            passed=not mismatches,
            actual=actual,
            expected=case.expected,
            mismatches=mismatches,
            description=case.description,
        )


# ── Helpers ────────────────────────────────────────────────────────────────
def _parse_dify_answer(answer: Any) -> dict[str, Any]:
    """Dify /v1/chat-messages 的 ``answer`` 字段是字符串。

    workflow 节点若返回 dict (LLM JSON mode),实际是字符串化的 JSON。
    尝试解析一次,失败返 ``{"answer": <raw>}``。
    """
    if isinstance(answer, dict):
        return answer
    if not isinstance(answer, str):
        return {"answer": answer}
    s = answer.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            import json
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            pass
    return {"answer": answer}


def _compare(actual: Any, expected: Any, *, path: str = "") -> list[str]:
    """Compare actual vs expected, return human-readable diffs.

    特殊:
      - expected 字符串 ``">=0.7"`` → 实际字段 >= 0.7 (numeric)
      - 字段以 ``_`` 开头 → 跳过(debug stash)
    """
    diffs: list[str] = []
    if isinstance(expected, dict):
        for k, v in expected.items():
            if k.startswith("_"):
                continue
            sub_path = f"{path}.{k}" if path else k
            if k not in actual:
                diffs.append(f"{sub_path}: missing")
            else:
                diffs.extend(_compare(actual[k], v, path=sub_path))
        return diffs
    if isinstance(expected, str) and expected.startswith(">="):
        try:
            threshold = float(expected[2:])
            actual_val = float(actual) if actual is not None else 0.0
            if actual_val < threshold:
                diffs.append(f"{path}: {actual_val} < {threshold}")
        except (TypeError, ValueError):
            diffs.append(f"{path}: cannot compare {actual!r} >= {threshold}")
        return diffs
    if actual != expected:
        diffs.append(f"{path}: {actual!r} != {expected!r}")
    return diffs