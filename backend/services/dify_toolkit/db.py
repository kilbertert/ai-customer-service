"""Dify PostgreSQL 访问层 (P0-C PR 2 — D8/D10 决策)。

C1 安全收敛: 干掉 `paramiko` SSH + `docker exec`,改用 basjoo-side 直连 Dify PG。
C2 升级适配: ``probe_workflows_schema()`` 在 deploy 开头探针,缺列 / 类型错即 raise
``DifySchemaError``(端点 502 + audit ``workflow.deploy_schema_mismatch``),
不静默 break(对 Dify 1.15+ schema 漂移,P0-B §6 升级时跑回归)。

DB 凭据来源: ``settings.dify_db_url``(P0-A 决策;Docker compose 默认
``postgresql://postgres:postgres@postgres:5432/dify``)。跨 host 走 TLS,凭据走 Vault。
basjoo 跟 Dify 默认共用同一 postgres docker-compose service → 同网络无问题。

公共 API:
  - ``probe_workflows_schema(conn)``      — 返回 ``{col_name: data_type}``
  - ``check_required_columns(actual)``    — 缺列 / 类型错返回列名 list
  - ``update_workflow_graph(conn, ...)``  — DB fallback 路径写 published row
  - ``get_conn()`` (context manager)      — pool 取/还连接
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

import psycopg2
import psycopg2.extensions
from psycopg2.pool import ThreadedConnectionPool

from .constants import DIFY_WORKFLOWS_REQUIRED_COLUMNS

logger = logging.getLogger(__name__)


# Module-level pool (lazy init) — 同一进程内共享一个 ThreadedConnectionPool;
# 第一次 ``get_conn()`` 时按 settings.dify_db_url 初始化,后续 get 直接 hit cache。
# 测试场景: conftest 调 ``_reset_pool_for_tests()`` 清空,避免泄漏 DB 句柄。
_pool: ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ThreadedConnectionPool:
    """Lazy-init the pool from settings.dify_db_url. Threadsafe.

    Import-time 故意不读 settings — 单元测试可能在 settings 不可用时 import db。
    """
    global _pool
    if _pool is not None:
        return _pool

    with _pool_lock:
        if _pool is not None:
            return _pool

        # 局部 import 避免循环依赖(settings 反向 import db 不可能,但保持 db 模块
        # 在 settings 出错时仍能 import,方便测试时 patch)
        from config import settings

        url = settings.dify_db_url
        if not url:
            raise RuntimeError(
                "DIFY_DB_URL is empty. Set settings.dify_db_url to "
                "'postgresql://user:pass@host:port/db' before deploy."
            )

        # minconn=1 / maxconn=8: deploy 路径串行,worker 数低;8 足够 burst。
        # 若需更高并发,ops 改 maxconn 而非调代码。
        _pool = ThreadedConnectionPool(minconn=1, maxconn=8, dsn=url)
        logger.info("Dify DB pool initialized (dsn=%s, maxconn=8)", _redact_dsn(url))
        return _pool


def _reset_pool_for_tests() -> None:
    """Test helper: close + clear module pool. conftest 在每个测试 module 结束调。"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception as exc:  # noqa: BLE001 — 测试收尾不阻断
                logger.debug("Dify DB pool closeall error: %s", exc)
            _pool = None


@contextmanager
def get_conn() -> Iterator[psycopg2.extensions.connection]:
    """取一条连接,用完归还 pool。``with get_conn() as conn:``。

    Raises:
        RuntimeError: pool 未初始化(``dify_db_url`` 缺失)
        psycopg2.OperationalError: DB 不可达 / 凭据错
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        # rollback any uncommitted txn before returning to pool
        try:
            if conn.closed == 0 and conn.status != psycopg2.extensions.STATUS_READY:
                conn.rollback()
        except Exception as exc:  # noqa: BLE001
            logger.debug("rollback on return failed: %s", exc)
        pool.putconn(conn)


# Schema probe (D10 决策) — 探针 SQL 读 information_schema 拿列名 + data_type。
# 比对 constants.DIFY_WORKFLOWS_REQUIRED_COLUMNS。缺列 / 类型错 → raise DifySchemaError
# → 端点 502。用 information_schema(ANSI 标准)而非 pg_catalog,跨 PG 11-15 兼容。
_PROBE_SQL = """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = %s
"""


def probe_workflows_schema(
    conn: psycopg2.extensions.connection,
) -> dict[str, str]:
    """读 ``workflows`` 表的实际列名 → data_type 映射。

    Returns:
        ``{"id": "uuid", "app_id": "uuid", ...}`` — 只含表里真实存在的列。

    Note:
        不抛 DifySchemaError — 那是 ``check_required_columns()`` 的职责。
        拆成两个函数让 deployer 可以 ``probe + check`` 拿到 ``actual`` 用于错误
        信息("实际是 X,期望是 Y")。
    """
    with conn.cursor() as cur:
        cur.execute(_PROBE_SQL, ("workflows",))
        rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}


def check_required_columns(
    actual: dict[str, str],
) -> list[str]:
    """比对 ``actual`` 跟 ``DIFY_WORKFLOWS_REQUIRED_COLUMNS``。

    Returns:
        list[str] — 缺 / 类型错的列名。空 list = 全部 OK。
    """
    missing: list[str] = []
    for col, expected_type in DIFY_WORKFLOWS_REQUIRED_COLUMNS.items():
        if col not in actual:
            missing.append(col)
        elif actual[col] != expected_type:
            # 类型错也算 missing — Dify 1.15+ 可能把 jsonb → json,text → varchar 等
            missing.append(col)
    return missing


# DB fallback write (D8 决策) — publish_workflow 失败时走 DB 直写 + audit。
# 镜像老 deployer.py:76-79 的 SQL,但参数化(old 是 %s + ::jsonb cast):
#   UPDATE workflows SET graph = %s::jsonb, updated_at = NOW()
#   WHERE app_id = %s AND version != 'draft' AND (%s::text IS NULL OR tenant_id = %s)
# 钉死 published row(Dify worker 读 published,不读 draft),tenant_id 过滤
# (Plan A 多租户共用单 Dify 时,只能动自己 tenant 的 row)。
_UPDATE_GRAPH_SQL = """
    UPDATE workflows
    SET graph = %s::jsonb,
        updated_at = NOW()
    WHERE app_id = %s
      AND version != 'draft'
      AND (%s::text IS NULL OR tenant_id = %s)
"""


def update_workflow_graph(
    conn: psycopg2.extensions.connection,
    *,
    app_id: str,
    graph: str,
    tenant_id: str | None = None,
) -> int:
    """DB fallback 写 published row 的 ``graph`` 字段。

    Args:
        conn: psycopg2 连接(由 ``get_conn()`` 给)
        app_id: Dify app UUID
        graph: JSON 字符串(``json.dumps(...)`` 后传入)
        tenant_id: 可选,多租户共用单 Dify 时过滤 row(Plan A 必备)

    Returns:
        int — 受影响行数(0 或 1)。0 = app 不存在 / 已被并发改 / tenant_id 不匹配。

    Note:
        不抛 DifyPublishError — 那是 deployer 的职责(包 SQL 异常 + audit)。
        deployer 捕获后写 ``AuditLog(action="workflow.deploy_db_fallback")``。
    """
    with conn.cursor() as cur:
        cur.execute(_UPDATE_GRAPH_SQL, (graph, app_id, tenant_id, tenant_id))
        rowcount = cur.rowcount
    conn.commit()
    logger.info(
        "Dify DB fallback wrote workflows.graph: app_id=%s tenant_id=%s rowcount=%d",
        app_id, tenant_id, rowcount,
    )
    return rowcount


def _redact_dsn(dsn: str) -> str:
    """DSN 脱敏: ``postgresql://user:pass@host:port/db`` → ``postgresql://user:***@host:port/db``"""
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    if "@" not in rest:
        return dsn
    creds, hostpart = rest.rsplit("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        return f"{scheme}://{user}:***@{hostpart}"
    return dsn
