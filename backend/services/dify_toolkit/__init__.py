"""M11+ P0-C — basjoo-side Dify workflow toolkit.

Build, validate, deploy and verify Dify workflow DSL files end-to-end via the
basjoo service layer (no SSH / docker exec / paramiko):

    from services.dify_toolkit import Workflow, StartNode, LLMNode, CodeNode, EndNode

    wf = Workflow(name="my_app", description="...")
    wf.add(StartNode(variables=[...]))
    wf.add(LLMNode(id="4080", title="classifier",
                   system_prompt="...", user_prompt="..."))
    wf.add(CodeNode(id="4002", title="safety_net",
                    code="def main(...): ..."))
    wf.add(EndNode(outputs=[...]))
    wf.connect("4001", "4080")
    wf.connect("4080", "4002")
    wf.connect("4002", "4099")

    yml_text = wf.to_yaml()

    from services.dify_toolkit import validate_yaml, Deployer
    validate_yaml(yml_text)

    deployer = Deployer.from_workspace(workspace)
    await deployer.deploy(
        yml=yml_text,
        app_id=agent.dify_app_id,
        actor_user_id=admin.id,
        correlation_id=str(uuid.uuid4()),
        db_session=async_session,
        tenant_id_for_audit=str(workspace.id),
    )

注: 原 tools/dify_workflow_toolkit/ 是 SSH 直连版本 (1,757 LOC, 含 paramiko + docker exec),
P0-C PR 1 把 builder/yml_validator 这 2 个 pure-python 模块 cp 过来 + 改 import 路径。
PR 2 重写 deployer/verifier/cli (走 DifyAdminClient + psycopg2 直连 Dify DB,
干掉 paramiko + docker inspect + AutoAddPolicy),并在 PR 2 收口加 4 个新模块
(constants / exceptions / db / deployer / verifier / cli)。

公共类一览:
  Builder: Workflow, StartNode, LLMNode, CodeNode, EndNode, IfElseNode,
           KnowledgeRetrievalNode, VariableAggregatorNode, Variable, Edge, Node
  Validate: validate_yaml, ValidationError
  Deploy:   Deployer, DeployResult, DifySchemaError, DifyPublishError
  Verify:   Verifier, TestCase, CaseResult, VerificationReport
"""

from .builder import (
    CodeNode,
    Edge,
    EndNode,
    IfElseNode,
    KnowledgeRetrievalNode,
    LLMNode,
    Node,
    StartNode,
    Variable,
    VariableAggregatorNode,
    Workflow,
)
from .exceptions import DifyPublishError, DifySchemaError
from .verifier import CaseResult, TestCase, VerificationReport, Verifier
from .yml_validator import ValidationError, validate_yaml

__version__ = "0.3.0-p0c-pr2"

# Lazy attribute proxies (PEP 562) — defer heavy transitive imports
# (notably psycopg2 via services.dify_toolkit.deployer → .db) until first
# access. This prevents the dev container from crashing on `import
# services.dify_toolkit` when psycopg2 isn't installed (CI/sandbox without
# Postgres direct driver).
_LAZY_ATTRS = {
    "Deployer": "services.dify_toolkit.deployer",
    "DeployResult": "services.dify_toolkit.deployer",
}


def __getattr__(name: str):  # PEP 562 module-level __getattr__
    if name in _LAZY_ATTRS:
        import importlib
        mod = importlib.import_module(_LAZY_ATTRS[name])
        value = getattr(mod, name)
        globals()[name] = value  # cache for next access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Builder
    "CodeNode",
    "Edge",
    "EndNode",
    "IfElseNode",
    "KnowledgeRetrievalNode",
    "LLMNode",
    "Node",
    "StartNode",
    "Variable",
    "VariableAggregatorNode",
    "Workflow",
    # Validate
    "validate_yaml",
    "ValidationError",
    # Deploy
    "Deployer",
    "DeployResult",
    "DifySchemaError",
    "DifyPublishError",
    # Verify
    "Verifier",
    "TestCase",
    "CaseResult",
    "VerificationReport",
]
