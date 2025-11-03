from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.schemas.user import UserResponseSchema, UserCreateSchema
from app.schemas.auth import TokenSchema
from app.crud import user as crud_user
from app.core.security import create_access_token
from app.api.deps import get_current_active_user
from app.models import User

router = APIRouter()

@router.post("/register", response_model=UserResponseSchema, status_code=status.HTTP_201_CREATED)
async def register(
        user_in: UserCreateSchema,
        db: AsyncSession = Depends(get_db)
):
    """用户注册"""
    # 检查用户名是否已存在
    user = await crud_user.get_user_by_username(db, username=user_in.username)
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被注册"
        )

    # 检查邮箱是否已存在
    user = await crud_user.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )

    # 创建用户
    user = await crud_user.create_user(db, user_schema=user_in)
    return user

@router.post("/login", response_model=TokenSchema)
async def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: AsyncSession = Depends(get_db)
):
    """用户登录"""
    user = await crud_user.authenticate_user(
        db,
        username=form_data.username,
        password=form_data.password
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户已被禁用"
        )

    # 创建访问令牌
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={
            "sub": str(user.id),  # 建议用字符串存储，避免JWT解析问题
            "username": user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
            "is_active": user.is_active
        }, expires_delta=access_token_expires
    )

    return TokenSchema(
        access_token=access_token,
        token_type="bearer"
    )

@router.post("/logout")
async def logout(current_user: User = Depends(get_current_active_user)):
    """用户登出（前端删除 token 即可）"""
    return {"message": "退出登录成功"}

@router.get("/me", response_model=UserResponseSchema)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """获取当前用户信息"""
    return current_user