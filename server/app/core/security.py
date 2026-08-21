"""
Security utilities for password hashing and JWT token generation.
"""
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from app.core.config import settings
from jose import JWTError, jwt


def _prehash(password: str) -> str:
    """
    Pre-hashes a password with SHA-256 to prevent bcrypt truncation.
    
    Args:
        password (str): The plaintext password.
        
    Returns:
        str: Base64-encoded SHA-256 hash.
    """
    digest = hashlib.sha256(password.encode()).digest()
    return base64.b64encode(digest).decode()


def hash_password(password: str) -> str:
    """
    Hashes a plaintext password using bcrypt.
    
    Args:
        password (str): The plaintext password.
        
    Returns:
        str: The bcrypt-hashed password string.
    """
    return bcrypt.hashpw(_prehash(password).encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verifies a plaintext password against a stored bcrypt hash.
    
    Args:
        plain (str): The plaintext password.
        hashed (str): The stored bcrypt hash.
        
    Returns:
        bool: True if the password matches, False otherwise.
    """
    return bcrypt.checkpw(_prehash(plain).encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a JWT access token for authentication.
    
    Args:
        subject (str): The subject (usually user ID) to encode in the token.
        expires_delta (Optional[timedelta]): Optional custom expiration duration.
        
    Returns:
        str: The encoded JWT access token.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> Optional[str]:
    """
    Decodes and validates a JWT access token.
    
    Args:
        token (str): The JWT access token to decode.
        
    Returns:
        Optional[str]: The subject (user ID) if valid, None if invalid or expired.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None
