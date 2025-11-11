from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
import os
import hashlib
from pathlib import Path
from datetime import datetime

from app.core.config import settings
from app.db.database import get_db
from app.models import User
from app.api.deps import get_current_active_user
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

# 确保上传目录存在
UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR = UPLOAD_DIR / "files"
FILES_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR = UPLOAD_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def calculate_file_hash(file_content: bytes) -> str:
    """计算文件内容的MD5哈希"""
    return hashlib.md5(file_content).hexdigest()


def get_storage_path(file_hash: str, original_filename: str | None) -> Path:
    """根据MD5哈希生成存储路径"""
    # 验证原始文件名
    if not original_filename:
        raise ValueError("原始文件名不能为空")
    
    if settings.use_hash_sharding:
        # 使用MD5前2位作为分片目录
        shard_dir = FILES_DIR / file_hash[:2]
        shard_dir.mkdir(parents=True, exist_ok=True)
        # 文件名：hash + 原扩展名
        file_extension = os.path.splitext(original_filename)[1]
        return shard_dir / f"{file_hash}{file_extension}"
    else:
        # 兼容旧版本：直接使用UUID
        import uuid
        file_extension = os.path.splitext(original_filename)[1]
        return UPLOAD_DIR / f"{uuid.uuid4()}{file_extension}"

@router.post("/upload")
async def upload_file(
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """上传附件（支持MD5去重）"""

    # 读取文件内容
    file_content = await file.read()
    file_size = len(file_content)
    
    # 检查文件大小限制
    if file_size > settings.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过限制 ({settings.max_upload_size / 1024 / 1024:.1f}MB)"
        )
    
    # 初始化变量
    file_path = None
    
    try:
        # 验证文件名
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文件名不能为空"
            )
        
        # 计算文件哈希
        file_hash = calculate_file_hash(file_content)
        
        # 生成存储路径
        file_path = get_storage_path(file_hash, file.filename)
        
        # 如果文件已存在（MD5相同），直接返回
        if file_path.exists():
            logger.info(f"文件已存在（MD5去重）: {file.filename}")
        else:
            # 保存新文件
            with open(file_path, "wb") as f:
                f.write(file_content)
            logger.info(f"新文件已保存: {file.filename} -> {file_path.name}")
        
        return {
            "filename": file_path.name,  # 存储的文件名（基于hash）
            "original_filename": file.filename,  # 原始文件名
            "file_size": file_size,
            "mime_type": file.content_type,
            "file_path": str(file_path),
            "file_hash": file_hash  # 返回hash用于去重判断
        }

    except Exception as e:
        # 清理文件
        if file_path is not None and file_path.exists():
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件上传失败: {str(e)}"
        )


@router.get("/upload/download/{filename}")
async def download_file(
        filename: str,
        current_user: User = Depends(get_current_active_user)
):
    """下载附件"""
    
    # 尝试在分片目录中查找文件
    file_path = None
    
    if settings.use_hash_sharding:
        # 从文件名提取hash前缀（去掉扩展名）
        file_hash = os.path.splitext(filename)[0]
        if len(file_hash) >= 2:
            shard_dir = FILES_DIR / file_hash[:2]
            potential_path = shard_dir / filename
            if potential_path.exists():
                file_path = potential_path
    
    # 如果分片目录中没找到，尝试在根目录查找
    if not file_path:
        potential_path = UPLOAD_DIR / filename
        if potential_path.exists():
            file_path = potential_path
    
    # 如果还是没找到，返回404
    if not file_path or not file_path.exists():
        logger.warning(f"文件不存在: {filename}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在"
        )
    
    logger.info(f"用户 {current_user.username} 下载文件: {filename}")
    
    # 返回文件，设置正确的响应头
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type='application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Access-Control-Expose-Headers': 'Content-Disposition'
        }
    )