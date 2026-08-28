"""实体名称规范化：与迁移 3d8f1a2b6c4d 的规范化规则保持一致（去除全部空白字符）。

用途：让“崇仁一中 · 高一（1）班”和“崇仁一中·高一（1）班”在唯一性上视为同名，
避免仅差空格的重复数据绕过租户内唯一约束。
"""
import re

_WS = re.compile(r"\s+")


def normalize_entity_name(name: str | None) -> str | None:
    if name is None:
        return None
    return _WS.sub("", name)
