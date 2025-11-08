"""
配置文件
app/core/config.py
"""
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseModel):
    # 数据库配置
    db_url: str = os.getenv("DB_URL", "sqlite+aiosqlite:///./pubmed_app.db")
    pdf_dir: str = os.getenv("PDF_DIR", "storage/pdfs")

    # NCBI 配置
    ncbi_tool: str = os.getenv("NCBI_TOOL", "test_tool")
    ncbi_email: str = os.getenv("NCBI_EMAIL", "zml0506@163.com")
    ncbi_api_key: str | None = os.getenv("NCBI_API_KEY") or None
    max_qps: float = 10.0 if os.getenv("NCBI_API_KEY") else 3.0

    # 项目信息
    project_name: str = "pubmed search"
    version: str = "1.0.0"
    api_prefix: str = "/api"

    # JWT 配置
    secret_key: str = "secretkeybyzhibenjwt"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7天

    # 文件上传配置
    upload_dir: str = os.getenv("UPLOAD_DIR", "./uploads")
    max_upload_size: int = int(os.getenv("MAX_UPLOAD_SIZE", str(30 * 1024 * 1024)))  # 30MB

    # CORS 配置
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "*",
    ]

    # 通义千问配置
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 模型配置
    qwen_max_model: str = "qwen-max"
    qwen_long_model: str = "qwen-long"
    qwen_vl_model: str = "qwen3-vl-plus"

    # ============================================
    # 检索配置
    # ============================================

    # 每次检索的目标文献数量
    max_search_results: int = int(os.getenv("MAX_SEARCH_RESULTS", "5"))

    # PDF 下载超时配置（秒）
    pdf_download_timeout: int = int(os.getenv("PDF_DOWNLOAD_TIMEOUT", "60"))  # 单个PDF下载超时
    pdf_extract_timeout: int = int(os.getenv("PDF_EXTRACT_TIMEOUT", "30"))    # 解压超时
    webview_timeout: int = int(os.getenv("WEBVIEW_TIMEOUT", "90"))            # 浏览器抓取超时

    # 检索限制
    max_pmids_to_fetch: int = int(os.getenv("MAX_PMIDS_TO_FETCH", "20"))      # 每次最多获取的PMID数量
    max_successful_downloads: int = int(os.getenv("MAX_SUCCESSFUL_DOWNLOADS", "5"))  # 成功下载多少个后停止

    # 重试配置
    pdf_download_max_retries: int = int(os.getenv("PDF_DOWNLOAD_MAX_RETRIES", "1"))  # PDF下载重试次数

    # 并发配置
    max_concurrent_downloads: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))  # 最大并发下载数

    # 检索倍数（检索数量 = 目标数量 * 倍数）
    search_multiplier: int = int(os.getenv("SEARCH_MULTIPLIER", "3"))


    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
