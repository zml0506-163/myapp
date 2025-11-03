from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseModel):
    db_url: str = os.getenv("DB_URL", "sqlite+aiosqlite:///./pubmed_app.db") #"mysql+aiomysql://root:@localhost:3306/pubmed_app?charset=utf8mb4"
    pdf_dir: str = os.getenv("PDF_DIR", "storage/pdfs")
    ncbi_tool: str = os.getenv("NCBI_TOOL", "test_tool")
    ncbi_email: str = os.getenv("NCBI_EMAIL", "zml0506@163.com")
    ncbi_api_key: str | None = os.getenv("NCBI_API_KEY") or None
    # Access rate control (NCBI recommends ≤ 3 req/s; 10 req/s with api_key)
    max_qps: float = 10.0 if os.getenv("NCBI_API_KEY") else 3.0

    # 项目信息
    project_name: str = "AI Chat Assistant"
    version: str = "1.0.0"
    api_prefix: str = "/api"

    # JWT 配置
    secret_key: str = "your-secret-key-change-in-production-please"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7天

    # 文件上传配置
    upload_dir: str = "./uploads"
    max_upload_size: int = 10 * 1024 * 1024  # 10MB

    # CORS 配置
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "*",
    ]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
