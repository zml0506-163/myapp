from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
import os
import uuid
from pathlib import Path

from app.core.config import settings
from app.db.database import get_db
from app.models import User
from app.api.deps import get_current_active_user

router = APIRouter()

# 确保上传目录存在
UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/upload")
async def upload_file(
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """上传附件"""

    # 检查文件大小
    file_size = 0
    chunk_size = 1024 * 1024  # 1MB

    # 生成唯一文件名
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = UPLOAD_DIR / unique_filename

    try:
        # 保存文件
        with open(file_path, "wb") as f:
            while chunk := await file.read(chunk_size):
                file_size += len(chunk)

                # 检查文件大小限制
                if file_size > settings.max_upload_size:
                    # 删除已写入的文件
                    f.close()
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件大小超过限制 ({settings.max_upload_size} 字节)"
                    )

                f.write(chunk)

        return {
            "filename": unique_filename,
            "original_filename": file.filename,
            "file_size": file_size,
            "mime_type": file.content_type,
            "file_path": str(file_path)
        }

    except Exception as e:
        # 清理文件
        if file_path.exists():
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件上传失败: {str(e)}"
        )