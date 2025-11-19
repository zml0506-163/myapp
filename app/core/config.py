"""
配置文件
app/core/config.py
"""
from pydantic import BaseModel
import os
import json
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
    
    # 文件存储策略配置
    use_hash_sharding: bool = True  # 是否使用MD5分片
    temp_file_cleanup_days: int = int(os.getenv("TEMP_FILE_CLEANUP_DAYS", "7"))  # 临时文件保留天数
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 从环境变量读取布尔值配置（避免 Pydantic 字段定义中使用复杂逻辑）
        self.use_hash_sharding = os.getenv("USE_HASH_SHARDING", "true").lower() == "true"
        self.log_console = os.getenv("LOG_CONSOLE", "true").lower() == "true"
        self.log_file = os.getenv("LOG_FILE", "true").lower() == "true"
        self.log_color = os.getenv("LOG_COLOR", "false").lower() == "true"
        self.use_redis_cache = os.getenv("USE_REDIS_CACHE", "false").lower() == "true"
        self.mcp_enabled = os.getenv("MCP_ENABLED", "false").lower() == "true"
        wl = os.getenv("MCP_TOOL_WHITELIST", "").strip()
        self.mcp_tool_whitelist = [x.strip() for x in wl.split(",") if x.strip()] if wl else []
        self.mcp_base_url = os.getenv("MCP_BASE_URL", "").strip()
        self.deliberate_enabled = os.getenv("DELIBERATE_ENABLED", "false").lower() == "true"

        # 可选：从 JSON 覆盖 MCP 配置（优先级高于环境变量）
        cfg_text = os.getenv("MCP_CONFIG_JSON", "").strip()
        cfg_path = os.getenv("MCP_CONFIG_PATH", "").strip()
        cfg = None
        if cfg_text:
            try:
                cfg = json.loads(cfg_text)
            except Exception:
                cfg = None
        elif cfg_path:
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = None
        if isinstance(cfg, dict):
            try:
                if "base_url" in cfg:
                    v = (cfg.get("base_url") or "").strip()
                    if v:
                        self.mcp_base_url = v
                if "enabled" in cfg and isinstance(cfg.get("enabled"), bool):
                    self.mcp_enabled = bool(cfg.get("enabled"))
                server = cfg.get("server") or {}
                if isinstance(server, dict) and isinstance(server.get("port"), int):
                    port = server.get("port"); assert isinstance(port, int)
                    self.mcp_server_port = int(port)
                auth = cfg.get("auth") or {}
                if isinstance(auth, dict):
                    if auth.get("header"):
                        self.mcp_auth_header = str(auth.get("header"))
                    if auth.get("token") is not None:
                        self.mcp_auth_token = str(auth.get("token"))
                to = cfg.get("timeouts") or {}
                if isinstance(to, dict):
                    if isinstance(to.get("request_seconds"), int):
                        req_sec = to.get("request_seconds")
                        assert isinstance(req_sec, int)
                        self.mcp_request_timeout_seconds = int(req_sec)
                    if isinstance(to.get("stream_seconds"), int):
                        stream_sec = to.get("stream_seconds")
                        assert isinstance(stream_sec, int)
                        self.mcp_stream_timeout_seconds = int(stream_sec)
                wl = cfg.get("whitelist")
                if isinstance(wl, list):
                    self.mcp_tool_whitelist = [str(x).strip() for x in wl if str(x).strip()]
            except Exception:
                # JSON 配置解析失败不应影响应用启动
                pass

    # CORS 配置
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "*",
    ]

    # DashScope 配置
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_base_url: str = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    # 模型配置
    qwen_max_model: str = os.getenv("QWEN_MAX_MODEL", "qwen-max")
    qwen_long_model: str = os.getenv("QWEN_LONG_MODEL", "qwen-long")
    qwen_vl_model: str = os.getenv("QWEN_VL_MODEL", "qwen-vl-plus")

    # ============================================
    # 检索配置
    # ============================================

    # 每次检索的目标文献数量
    max_search_results: int = int(os.getenv("MAX_SEARCH_RESULTS", "5"))

    # PDF 下载超时配置（秒）
    pdf_download_timeout: int = int(os.getenv("PDF_DOWNLOAD_TIMEOUT", "60"))  # 兼容字段（不再作为总超时使用）
    pdf_download_total_timeout: int = int(os.getenv("PDF_DOWNLOAD_TOTAL_TIMEOUT", "300"))  # 总超时（默认5分钟）
    pdf_download_idle_timeout: int = int(os.getenv("PDF_DOWNLOAD_IDLE_TIMEOUT", "60"))     # 空闲超时（无新数据）
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

    # LLM 限流重试配置
    llm_rate_limit_retry_wait_seconds: int = int(os.getenv("LLM_RATE_LIMIT_RETRY_WAIT_SECONDS", "15"))
    llm_rate_limit_max_retries: int = int(os.getenv("LLM_RATE_LIMIT_MAX_RETRIES", "3"))

    # ============================================
    # 日志配置
    # ============================================
    log_level: str = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_dir: str = os.getenv("LOG_DIR", "./logs")  # 日志文件目录
    log_console: bool = False  # 是否输出到控制台
    log_file: bool = False  # 是否输出到文件
    log_color: bool = False  # 控制台是否使用彩色输出

    # ============================================
    # Redis 缓存配置
    # ============================================
    use_redis_cache: bool = False  # 是否使用 Redis 缓存
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # Redis 连接地址
    redis_cache_expire: int = int(os.getenv("REDIS_CACHE_EXPIRE", "3600"))  # Redis 缓存默认过期时间（秒）

    # ============================================
    # 路由展示开关（仅展示计划日志，不改流程）
    # ============================================

    # ============================================
    # MCP 相关配置
    # ============================================
    mcp_enabled: bool = False
    mcp_server_port: int = int(os.getenv("MCP_SERVER_PORT", "0"))
    mcp_tool_whitelist: list[str] = []
    mcp_base_url: str = os.getenv("MCP_BASE_URL", "")
    # MCP HTTP 客户端配置
    mcp_request_timeout_seconds: int = int(os.getenv("MCP_REQUEST_TIMEOUT_SECONDS", "30"))
    mcp_stream_timeout_seconds: int = int(os.getenv("MCP_STREAM_TIMEOUT_SECONDS", "120"))
    mcp_auth_header: str = os.getenv("MCP_AUTH_HEADER", "Authorization")
    mcp_auth_token: str = os.getenv("MCP_AUTH_TOKEN", "")

    # ============================================
    # 深度思考/评审（展示型开关，默认关闭）
    # ============================================
    deliberate_enabled: bool = False
    deliberate_budget_tokens: int = int(os.getenv("DELIBERATE_BUDGET_TOKENS", "0"))
    deliberate_max_time_ms: int = int(os.getenv("DELIBERATE_MAX_TIME_MS", "0"))


    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
