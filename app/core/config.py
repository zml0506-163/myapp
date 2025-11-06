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
    secret_key: str = "secretkeybyzhibenjwt"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7天

    # 文件上传配置
    upload_dir: str = "./uploads"
    max_upload_size: int = 30 * 1024 * 1024  # 30MB

    # CORS 配置
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "*",
    ]

    # 通义千问配置
    dashscope_api_key: str = "sk-8f7373b5086249e3b0db5bb3609cc909"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 模型配置
    qwen_max_model: str = "qwen-max"
    qwen_long_model: str = "qwen-long"
    qwen_vl_model: str = "qwen3-vl-plus"

    # 检索配置
    max_search_results: int = 5

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
