from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError

from app.core.config import settings
from app.schemas.user import UserResponseSchema

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

async def get_current_user(
        token: str = Depends(oauth2_scheme)
) -> UserResponseSchema:  # 或直接返回User对象（如果需要兼容现有逻辑）
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        # 从payload提取字段
        user_id: Optional[str] = payload.get("sub")
        username: Optional[str] = payload.get("username")
        email: Optional[str] = payload.get("email")
        is_superuser: Optional[bool] = payload.get("is_superuser")
        is_active: Optional[bool] = payload.get("is_active")

        # 校验必要字段是否存在
        if not all([user_id, username, email, is_superuser is not None, is_active is not None]):
            raise credentials_exception

        # 确保user_id不是None再转换为int
        if user_id is None:
            raise credentials_exception
        
        # 类型断言，告诉类型检查器user_id在这里不可能是None
        assert user_id is not None
        
        # 返回用户信息（可根据需要返回User对象或TokenUser）
        return UserResponseSchema(
            id=int(user_id),
            username=username,  # type: ignore
            email=email,  # type: ignore
            is_superuser=is_superuser,  # type: ignore
            is_active=is_active  # type: ignore
        )
    except JWTError:
        raise credentials_exception

async def get_current_active_user(
        current_user: UserResponseSchema = Depends(get_current_user)
) -> UserResponseSchema:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user