from pydantic import BaseModel, EmailStr

# 用户基础 Schema
class UserBaseSchema(BaseModel):
    email: EmailStr
    username: str

# 用户创建 Schema
class UserCreateSchema(BaseModel):
    username: str
    email: EmailStr
    password: str

# 用户更新 Schema
class UserUpdateSchema(BaseModel):
    email: EmailStr | None = None
    password: str | None = None

# 用户响应 Schema（返回给前端）
class UserResponseSchema(UserBaseSchema):
    id: int
    is_active: bool
    is_superuser: bool

    class Config:
        from_attributes = True

# 用户登录 Schema
class UserLoginSchema(BaseModel):
    username: str
    password: str