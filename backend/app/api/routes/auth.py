from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core import security
from app.db.session import get_db
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import UserCreate, User as UserSchema, ForgotPasswordRequest, ResetPasswordRequest
from app.api.deps import get_current_user
from app.services.email_service import EmailService
import secrets
import time

router = APIRouter()

@router.post("/login/access-token", response_model=Token)
async def login_access_token(
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    result = await db.execute(select(User).filter(User.email == form_data.username))
    user = result.scalars().first()
    
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )
        
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

@router.post("/register", response_model=UserSchema)
async def register_user(
    *,
    db: AsyncSession = Depends(get_db),
    user_in: UserCreate,
) -> Any:
    """
    Register a new user.
    """
    result = await db.execute(select(User).filter(User.email == user_in.email))
    user = result.scalars().first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    
    user_obj = User(
        email=user_in.email,
        hashed_password=security.get_password_hash(user_in.password),
        is_active=True,
        is_superuser=False,
    )
    db.add(user_obj)
    try:
        await db.commit()
    except IntegrityError:
        # The same email was registered by a simultaneous request (the check above and this insert are not atomic).
        await db.rollback()
        raise HTTPException(status_code=400, detail="The user with this username already exists in the system.")
    await db.refresh(user_obj)
    return user_obj

@router.get("/me", response_model=UserSchema)
async def read_users_me(
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get current user.
    """
    return current_user

@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Password reset request
    """
    result = await db.execute(select(User).filter(User.email == request.email))
    user = result.scalars().first()
    
    # Generic message even if user doesn't exist
    generic_msg = {"message": "If an account exists for this email, a password reset link has been sent."}
    
    if not user:
        return generic_msg
        
    current_time = int(time.time())
    
    # Rate limit: max 1 request per minute
    if user.password_reset_requested_at and current_time - user.password_reset_requested_at < 60:
        return generic_msg

    # Generate a secure token
    raw_token = secrets.token_urlsafe(32)
    hashed_token = security.get_password_hash(raw_token)
    
    user.password_reset_token = hashed_token
    user.password_reset_expires_at = current_time + (15 * 60) # 15 minutes expiration
    user.password_reset_requested_at = current_time
    
    await db.commit()
    
    # Include user ID in the token string for fast lookup
    combined_token = f"{user.id}:{raw_token}"
    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={combined_token}"
    
    EmailService.send_password_reset(user.email, reset_link)
    
    return generic_msg

@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Reset password
    """
    try:
        user_id_str, raw_token = request.token.split(":")
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token format")
        
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    
    if not user or not user.password_reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
        
    current_time = int(time.time())
    if not user.password_reset_expires_at or current_time > user.password_reset_expires_at:
        raise HTTPException(status_code=400, detail="Token has expired")
        
    if not security.verify_password(raw_token, user.password_reset_token):
        raise HTTPException(status_code=400, detail="Invalid token")
        
    # Update password and invalidate token
    user.hashed_password = security.get_password_hash(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    
    await db.commit()
    
    return {"message": "Password reset successfully."}
