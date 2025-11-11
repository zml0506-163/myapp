"""
日志管理模块 - 统一日志配置
app/core/logger.py

使用方式:
    from app.core.logger import logger
    
    logger.debug("调试信息")
    logger.info("一般信息")
    logger.warning("警告信息")
    logger.error("错误信息")
    logger.exception("异常信息（自动记录堆栈）")
"""
import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
import os
from datetime import datetime


class LoggerManager:
    """日志管理器 - 单例模式"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self.logger = logging.getLogger("pubmed_app")
        
        # 避免重复添加 handler
        if self.logger.handlers:
            return
            
        # 从环境变量读取配置
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        log_dir = os.getenv("LOG_DIR", "./logs")
        enable_console = os.getenv("LOG_CONSOLE", "true").lower() == "true"
        enable_file = os.getenv("LOG_FILE", "true").lower() == "true"
        
        # 设置日志级别
        self.logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        # 创建日志目录
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # 统一的日志格式
        # 格式: 2025-01-10 15:30:45 | INFO | app.api.v1.chat:115 | chat_stream | 开始处理聊天请求
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(funcName)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # ============================================
        # 1. 控制台输出 Handler
        # ============================================
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.DEBUG)
            
            # 控制台使用彩色格式（可选）
            if os.getenv("LOG_COLOR", "false").lower() == "true":
                console_handler.setFormatter(ColoredFormatter(
                    fmt='%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(funcName)s | %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                ))
            else:
                console_handler.setFormatter(formatter)
            
            self.logger.addHandler(console_handler)
        
        # ============================================
        # 2. 文件输出 Handler - 按天滚动
        # ============================================
        if enable_file:
            # 主日志文件（所有级别）
            all_log_file = log_path / "app.log"
            all_handler = TimedRotatingFileHandler(
                filename=all_log_file,
                when='midnight',  # 每天午夜滚动
                interval=1,
                backupCount=30,  # 保留30天
                encoding='utf-8'
            )
            all_handler.suffix = "%Y-%m-%d"  # 日志文件后缀格式
            all_handler.setLevel(logging.DEBUG)
            all_handler.setFormatter(formatter)
            self.logger.addHandler(all_handler)
            
            # 错误日志文件（ERROR及以上）
            error_log_file = log_path / "error.log"
            error_handler = TimedRotatingFileHandler(
                filename=error_log_file,
                when='midnight',
                interval=1,
                backupCount=90,  # 错误日志保留更久
                encoding='utf-8'
            )
            error_handler.suffix = "%Y-%m-%d"
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(formatter)
            self.logger.addHandler(error_handler)
        
        # 防止日志向上传播到根logger
        self.logger.propagate = False
        
        # 记录初始化信息
        self.logger.info(f"日志系统初始化完成 | 级别: {log_level} | 目录: {log_path.absolute()}")
    
    def get_logger(self, name: str | None = None):
        """
        获取指定模块的logger
        
        Args:
            name: 模块名称，如果为None则返回根logger
            
        Returns:
            Logger实例
        """
        if name:
            return self.logger.getChild(name)
        return self.logger


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器（用于控制台输出）"""
    
    # ANSI 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }
    
    def format(self, record):
        # 添加颜色
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        return super().format(record)


# ============================================
# 全局 Logger 实例
# ============================================
_manager = LoggerManager()
logger = _manager.get_logger()


# ============================================
# 便捷函数：为特定模块创建 logger
# ============================================
def get_logger(name: str):
    """
    为特定模块获取logger
    
    使用示例:
        from app.core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("模块日志")
    """
    return _manager.get_logger(name)
