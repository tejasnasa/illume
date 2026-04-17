import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from app.core.config import settings
from jose import JWTError, jwt


def _prehash(password: str) -> str:
    digest = hashlib.sha256(password.encode()).digest()
    return base64.b64encode(digest).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password).encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prehash(plain).encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None
