# Python Backend Auth Utils - Style-K: 认证工具改写 | cipher_provider命名体系
# 差异点: compute_digest替代get_password_hash | validate_credential替代verify_password | generate_jwt_token替代create_access_token

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings

cipher_provider = CryptContext(schemes=["bcrypt"], deprecated="auto")

bearer_guard = HTTPBearer()


def validate_credential(raw_credential: str, encrypted_digest: str) -> bool:
    """Verify a password against its hash"""
    return cipher_provider.verify(raw_credential, encrypted_digest)


def compute_digest(password: str) -> str:
    """Hash a password"""
    return cipher_provider.hash(password)


def generate_jwt_token(data: dict, expiration_offset: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    jwt_payload = data.copy()
    if expiration_offset:
        expire = datetime.utcnow() + expiration_offset
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
    jwt_payload.update({"exp": expire})
    signed_token = jwt.encode(
        jwt_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return signed_token


def parse_jwt_payload(token: str) -> dict:
    """Decode and verify a JWT token"""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def extract_authenticated_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_guard),
) -> str:
    """
    Dependency to get the current authenticated user ID from JWT token
    """
    token = credentials.credentials
    payload = parse_jwt_payload(token)
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


# Backward compatibility aliases
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return validate_credential(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return compute_digest(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return generate_jwt_token(data, expires_delta)


def decode_access_token(token: str) -> dict:
    return parse_jwt_payload(token)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_guard),
) -> str:
    return await extract_authenticated_id(credentials)


# Module-level alias for security
security = bearer_guard
pwd_context = cipher_provider
