# Python Backend Auth Routes - Style-J: 认证路由改写 | enroll_account命名体系
# 差异点: enroll_account替代register | authenticate_session替代login | account_record替代user_doc

from fastapi import APIRouter, HTTPException, status, Depends
from models import UserCreate, LoginRequest, Token, UserResponse
from auth import (
    compute_digest,
    validate_credential,
    generate_jwt_token,
    extract_authenticated_id,
)
from database import cosmos_db
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=Token, status_code=status.HTTP_200_OK)
async def register(account_params: UserCreate):
    """
    Register a new user account
    """
    try:
        logger.info(f"Registration attempt for email: {account_params.email}")
        prior_account = cosmos_db.get_user_by_email(account_params.email)
        if prior_account:
            logger.warning(f"Registration failed: Email already exists {account_params.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists",
            )

        account_id = str(uuid.uuid4())
        account_record = {
            "id": account_id,
            "username": account_params.username,
            "email": account_params.email,
            "hashed_password": compute_digest(account_params.password),
            "created_at": datetime.utcnow().isoformat(),
        }

        persisted_account = cosmos_db.create_user(account_record)
        logger.info(f"User created successfully: {account_params.email}")

        signed_token = generate_jwt_token(
            data={"sub": account_id, "email": account_params.email}
        )

        account_response = UserResponse(
            id=persisted_account["id"],
            username=persisted_account["username"],
            email=persisted_account["email"],
            createdAt=persisted_account["created_at"],
        )

        return Token(token=signed_token, user=account_response)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Registration validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register user: {str(e)}",
        )


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
async def login(credential_payload: LoginRequest):
    """
    Authenticate user and receive access token
    """
    try:
        logger.info(f"Login attempt for email: {credential_payload.email}")
        account_entity = cosmos_db.get_user_by_email(credential_payload.email)
        if not account_entity:
            logger.warning(f"Login failed: User not found for email {credential_payload.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not validate_credential(credential_payload.password, account_entity["hashed_password"]):
            logger.warning(f"Login failed: Invalid password for email {credential_payload.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        signed_token = generate_jwt_token(
            data={"sub": account_entity["id"], "email": account_entity["email"]}
        )

        account_response = UserResponse(
            id=account_entity["id"],
            username=account_entity["username"],
            email=account_entity["email"],
            createdAt=account_entity["created_at"],
        )

        logger.info(f"Login successful for user: {account_entity['email']}")
        return Token(token=signed_token, user=account_response)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to login: {str(e)}",
        )
