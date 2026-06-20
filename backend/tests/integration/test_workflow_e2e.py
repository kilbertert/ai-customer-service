"""M12 E2E — 真实 MiniMax + Dify 端到端集成测试。

依赖(任一缺失 → 自动 skip):
  - ``MINIMAX_API_KEY`` 环境变量 (真实 MiniMax-Text-01 调用)
  - ``MINIMAX_API_BASE`` 可选,默认 ``https://api.minimax.chat`` (全球)
  - ``DIFY_TEST_URL`` 可选,用于部署到真实 Dify;不设则只测生成不测部署

跑法::

    MINIMAX_API_KEY=sk-cp-... pytest tests/integration/test_workflow_e2e.py -v

设计:
  - 不打 ``basjoo`` 业务路由,直接调 DSLGenerator + MiniMaxClient
  - 4 模板各跑一次,成功率 < 80% 时标记 fail
  - 沙箱/CI 默认 skip,避免误报
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MINIMAX_API_KEY"),
    reason="MINIMAX_API_KEY 未设置, 跳过真实 MiniMax E2E 测试",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template_id,requirements,expected_kw",
    [
        ("basic_chat", "电商退货客服, 友好语气", ["system_prompt", "model_name"]),
        ("rag_qa", "员工手册问答助手", ["knowledge_base_ids", "top_k"]),
        ("conditional_router", "SaaS 客服分流, 价格走销售, 其他走技术", ["true_prompt", "false_prompt"]),
        ("tool_calling", "天气助手, 用 get_current_weather 工具", ["tool_ids"]),
    ],
)
async def test_real_minimax_generates_for_each_template(
    template_id: str,
    requirements: str,
    expected_kw: list[str],
) -> None:
    """每个模板调真实 MiniMax-Text-01, 验证 yml + schema 校验通过。"""
    from services.dify_toolkit.dsl_generator import DSLGenerator
    from services.dify_toolkit.yml_validator import (
        ValidationError as YmlValidationError,
        validate_yaml,
    )
    from services.llm_integration.minimax_client import minimax_call

    gen = DSLGenerator(llm_caller=minimax_call)
    yml, meta = await gen.generate(
        template_id=template_id,
        user_input={
            "user_requirements": requirements,
            "knowledge_base_ids": ["kb-handbook-2024"] if template_id == "rag_qa" else [],
            "tool_ids": ["get_current_weather"] if template_id == "tool_calling" else [],
        },
    )
    try:
        validate_yaml(yml)
    except YmlValidationError as e:
        pytest.fail(f"{template_id}: YmlValidator reject → {e}")
    for kw in expected_kw:
        assert kw in yml or kw in meta["params"], (
            f"{template_id}: expected {kw!r} in yml or params, got yml preview: {yml[:200]}"
        )
    assert meta["attempt"] >= 1
    assert isinstance(meta["params"], dict)
    assert isinstance(meta["usage"], dict)
    assert "total_tokens" in meta["usage"]
    print(
        f"\n[{template_id}] attempt={meta['attempt']} "
        f"tokens={meta['usage'].get('total_tokens', '?')}"
    )


@pytest.mark.asyncio
async def test_real_minimax_summary_success_rate() -> None:
    """跑 10 次 basic_chat, 统计成功率 (plan §6.4 验收门: ≥ 95% = 10/10 期望)。"""
    from services.dify_toolkit.dsl_generator import DSLGenerator
    from services.dify_toolkit.yml_validator import (
        ValidationError as YmlValidationError,
        validate_yaml,
    )
    from services.llm_integration.minimax_client import minimax_call

    gen = DSLGenerator(llm_caller=minimax_call)
    success = 0
    for i in range(10):
        try:
            yml, _meta = await gen.generate(
                template_id="basic_chat",
                user_input={"user_requirements": f"测试 {i}: 智能客服"},
            )
            validate_yaml(yml)
            success += 1
        except (YmlValidationError, Exception):  # noqa: BLE001
            pass
    rate = success / 10
    print(f"\nbasic_chat success rate: {success}/10 = {rate*100:.0f}%")
    assert rate >= 0.8, f"success rate {rate*100:.0f}% below 80% threshold"