"""
文件处理服务 - 支持多格式、缓存、压缩
app/services/file_service.py
"""
import hashlib
import os
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from PIL import Image
from sqlalchemy import select, func
from openai import OpenAI, NotFoundError

from app.core.config import settings
from app.db.database import get_db_session
from app.models import FileCache
from app.core.logger import get_logger

logger = get_logger(__name__)


class FileService:
    """文件处理服务"""

    # 支持的文件格式
    SUPPORTED_FORMATS = {
        'image': {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'},
        'document': {'.txt', '.docx', '.pdf', '.md', '.csv', '.json'},
        'spreadsheet': {'.xlsx'},
        'ebook': {'.epub', '.mobi'}
    }

    def __init__(self):
        self.client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
        self.temp_dir = Path(settings.upload_dir) / "temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.MAX_PIXELS = 8190  # 像素限制
        self.MIN_COMPRESS_FILE_SIZE = 2 * 1024 * 1024  # 5MB
        
        # 文件名映射缓存（用于记录临时文件名 -> 原始文件名）
        self.filename_mapping = {}  # {temp_filename: original_filename}

    def calculate_file_md5(self, file_path: str) -> str:
        """计算文件MD5值"""
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def get_file_type(self, file_path: str) -> str:
        """获取文件类型"""
        ext = Path(file_path).suffix.lower()

        if ext in self.SUPPORTED_FORMATS['image']:
            return 'image'
        elif ext in self.SUPPORTED_FORMATS['document']:
            return 'document'
        elif ext in self.SUPPORTED_FORMATS['spreadsheet']:
            return 'spreadsheet'
        elif ext in self.SUPPORTED_FORMATS['ebook']:
            return 'ebook'
        else:
            return 'unknown'

    def compress_image(self, input_path: str, quality: int = 85) -> str:
        """
        压缩图片

        Args:
            input_path: 输入图片路径
            quality: 压缩质量 (1-100)

        Returns:
            压缩后的图片路径
        """
        try:
            output_path = self.temp_dir / f"compressed_{Path(input_path).name}"

            with Image.open(input_path) as img:
                # 转换为RGB（处理RGBA等格式）
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = rgb_img

                # 压缩保存
                img.save(output_path, "JPEG", optimize=True, quality=quality)

            # 检查压缩效果
            original_size = os.path.getsize(input_path)
            compressed_size = os.path.getsize(output_path)

            logger.debug(f"图片压缩: {original_size / 1024:.1f}KB -> {compressed_size / 1024:.1f}KB")

            # 如果压缩后反而更大，使用原图
            if compressed_size >= original_size:
                return input_path

            return str(output_path)

        except Exception as e:
            logger.warning(f"图片压缩失败: {e}")
            return input_path

    def resize_image_by_pixels(self, input_path: str) -> str:
        """调整图片尺寸，确保宽/高均不超过MAX_PIXELS"""
        input_path_obj = Path(input_path)
        try:
            with Image.open(input_path_obj) as img:
                width, height = img.size

                # 检查是否超过像素限制
                if width <= self.MAX_PIXELS and height <= self.MAX_PIXELS:
                    return str(input_path_obj)  # 无需调整

                # 计算缩放比例（取最小比例，确保宽高均不超限）
                scale = min(self.MAX_PIXELS / width, self.MAX_PIXELS / height)
                new_width = int(width * scale)
                new_height = int(height * scale)

                # 高质量缩放（保留原图模式，避免不必要的格式转换）
                resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # 保存调整后的图片
                output_path = self.temp_dir / f"resized_{input_path_obj.name}"
                # 根据原图格式保存（优先保留原图格式）
                format = img.format or "JPEG"
                resized_img.save(output_path, format=format, optimize=True)

                logger.debug(f"图片尺寸调整: {width}x{height} -> {new_width}x{new_height}")
                return str(output_path)

        except Exception as e:
            logger.warning(f"图片尺寸调整失败: {e}")
            return str(input_path_obj)  # 失败时返回原图

    async def verify_file_id(self, file_id: str) -> bool:
        """验证qwen-long的file_id是否有效"""
        try:
            file_info = self.client.files.retrieve(file_id=file_id)
            return file_info.status in ('uploaded', 'completed')
        except NotFoundError:
            return False
        except Exception as e:
            logger.warning(f"验证file_id失败: {e}")
            return False

    async def get_or_upload_file(self, file_path: str, original_filename: Optional[str] = None) -> Optional[str]:
        """
        获取或上传文件到qwen-long

        优先从缓存获取，缓存无效则重新上传
        
        Args:
            file_path: 文件路径
            original_filename: 原始文件名（用于显示给用户）

        Returns:
            qwen-long的file_id
        """
        # 如果没有提供原始文件名，使用路径中的文件名
        if not original_filename:
            original_filename = Path(file_path).name
        # 1. 计算MD5
        file_md5 = self.calculate_file_md5(file_path)

        # 2. 查询缓存
        async with get_db_session() as db:
            result = await db.execute(
                select(FileCache).where(FileCache.file_md5 == file_md5)
            )
            cached = result.scalar_one_or_none()

            # 3. 如果有缓存，验证有效性
            if cached and cached.is_valid:
                is_valid = await self.verify_file_id(cached.qwen_file_id)

                if is_valid:
                    # 更新使用统计
                    cached.usage_count += 1
                    cached.last_used_at = func.now()
                    cached.last_verified_at = func.now()
                    await db.commit()

                    logger.info(f"使用缓存文件: {cached.original_filename} (file_id: {cached.qwen_file_id})")
                    return cached.qwen_file_id
                else:
                    # 标记为无效
                    cached.is_valid = False
                    await db.commit()

            # 4. 上传新文件
            try:
                # 图片压缩
                file_type = self.get_file_type(file_path)
                upload_path = file_path

                if file_type == 'image':
                    # 1. 先检查并调整像素（避免像素超限错误）
                    resized_path = self.resize_image_by_pixels(file_path)
                    file_size = os.path.getsize(resized_path)

                    # 2. 再根据文件大小决定是否压缩（大于5MB则压缩）
                    if file_size > self.MIN_COMPRESS_FILE_SIZE:
                        upload_path = self.compress_image(resized_path)
                    else:
                        upload_path = resized_path
                    
                    # 记录文件名映射（临时文件名 -> 原始文件名）
                    temp_filename = Path(upload_path).name
                    self.filename_mapping[temp_filename] = original_filename

                    logger.debug(f"图片处理: {original_filename} -> {temp_filename} ({file_size / 1024:.1f}KB)")
                else:
                    logger.debug(f"准备上传: {original_filename}")

                # 上传到qwen-long(使用原始文件名作为显示名,purpose必须为file-extract)
                with open(upload_path, 'rb') as f:
                    file_object = self.client.files.create(
                        file=(original_filename, f),  # 关键:使用原始文件名
                        purpose="file-extract"  # type: ignore # qwen-long要求使用file-extract
                    )

                logger.info(f"文件上传成功: {original_filename} -> {file_object.id}")

                # 5. 保存到缓存
                if cached:
                    # 更新现有记录
                    cached.qwen_file_id = file_object.id
                    cached.qwen_status = file_object.status
                    cached.is_valid = True
                    cached.last_verified_at = func.now()
                    cached.usage_count = 1
                    cached.last_used_at = func.now()
                else:
                    # 创建新记录（使用原始文件的信息）
                    new_cache = FileCache(
                        file_md5=file_md5,
                        original_filename=original_filename,  # 保存原始文件名
                        file_path=file_path,  # 使用原始路径
                        file_size=os.path.getsize(file_path),
                        mime_type=None,
                        qwen_file_id=file_object.id,
                        qwen_status=file_object.status,
                        is_valid=True,
                        last_verified_at=func.now(),
                        usage_count=1,
                        last_used_at=func.now()
                    )
                    db.add(new_cache)

                await db.commit()

                return file_object.id

            except Exception as e:
                logger.error(f"文件上传失败: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                return None

    async def process_attachments(
            self,
            attachments: List[Dict]
    ) -> Tuple[List[str], bool]:
        """
        处理附件列表

        Returns:
            (file_ids列表, 是否只有图片)
        """
        file_ids = []
        has_non_image = False

        for att in attachments:
            file_path = att.get('file_path')
            if not file_path or not os.path.exists(file_path):
                continue

            file_type = self.get_file_type(file_path)

            # 检查是否有非图片文件
            if file_type != 'image':
                has_non_image = True

            # 获取原始文件名（关键：传递给阿里）
            original_filename = att.get('original_filename', Path(file_path).name)
            
            # 获取file_id
            file_id = await self.get_or_upload_file(file_path, original_filename)
            if file_id:
                file_ids.append(file_id)

        only_images = not has_non_image

        return file_ids, only_images

    async def build_file_context(self, file_ids: List[str]) -> str:
        """构建文件上下文字符串（用于qwen-long的system消息）"""
        if not file_ids:
            return ""

        return ",".join([f"fileid://{fid}" for fid in file_ids])

    def cleanup_temp_files(self):
        """清理临时文件"""
        try:
            for file in self.temp_dir.glob("compressed_*"):
                if file.is_file():
                    file.unlink()
        except Exception as e:
            logger.warning(f"清理临时文件失败: {e}")


# 全局实例
file_service = FileService()