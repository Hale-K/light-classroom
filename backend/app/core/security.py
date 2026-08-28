"""安全模块 - JWT 认证 + 密码哈希"""
from datetime import datetime, timedelta, timezone
from typing import Any
import bcrypt
from jose import jwt
from app.core.config import settings


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码（bcrypt）"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（bcrypt）"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    """生成 JWT access token

    subject 通常为 user_id；extra 可携带 school_code 等业务上下文。
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    to_encode = {"sub": str(subject), "exp": expire}
    if extra:
        to_encode.update(extra)
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_admin_access_token(admin_id: str | int) -> str:
    """平台超管令牌：scope=admin，与学校内用户令牌隔离（get_current_admin 校验）"""
    return create_access_token(admin_id, {"scope": "admin", "tid": None})


def decode_access_token(token: str) -> dict[str, Any]:
    """解码 JWT，返回 payload"""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
