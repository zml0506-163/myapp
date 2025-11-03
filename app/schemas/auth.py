from pydantic import BaseModel

class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenPayloadSchema(BaseModel):
    sub: int | None = None