"""Password complexity validator.

Spec deviation (M11 PR3): spec 引用 ``backend/libs/password.py`` 但 libs 目录不存在,
新增本模块提供 ``valid_password`` 入口。规则: 长度 8-128 + 至少 1 大写 + 1 小写 + 1 数字。
"""
import re

_MIN_LENGTH = 8
_MAX_LENGTH = 128
_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).+$"
)


def valid_password(password: str) -> bool:
    if not isinstance(password, str):
        return False
    if len(password) < _MIN_LENGTH or len(password) > _MAX_LENGTH:
        return False
    return bool(_PATTERN.match(password))
