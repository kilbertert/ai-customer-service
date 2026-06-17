"""M11 PR3 — 临时邮箱域名黑名单(loader + check)。

黑名单文件路径: backend/security/email_blacklist.txt
内容: 每行一个域名,以 ``#`` 开头为注释。
"""
from pathlib import Path

_BLACKLIST_PATH = Path(__file__).parent / "email_blacklist.txt"
_BLACKLIST_CACHE: set[str] | None = None


def _load_blacklist() -> set[str]:
    global _BLACKLIST_CACHE
    if _BLACKLIST_CACHE is not None:
        return _BLACKLIST_CACHE
    raw = _BLACKLIST_PATH.read_text(encoding="utf-8")
    domains: set[str] = set()
    for line in raw.splitlines():
        stripped = line.strip().lower()
        if not stripped or stripped.startswith("#"):
            continue
        domains.add(stripped)
    _BLACKLIST_CACHE = domains
    return domains


def is_blacklisted_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in _load_blacklist()


def reload_blacklist() -> None:
    """测试用 — 清空缓存以便下次重新读盘。"""
    global _BLACKLIST_CACHE
    _BLACKLIST_CACHE = None
