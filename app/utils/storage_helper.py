"""
文件存储路径管理工具
app/utils/storage_helper.py
"""
from pathlib import Path
from datetime import datetime
from typing import Optional
from app.core.config import settings


class StorageHelper:
    """文件存储路径管理"""
    
    def __init__(self):
        self.pdf_dir = Path(settings.pdf_dir)
        self.upload_dir = Path(settings.upload_dir)
        
    def get_pdf_storage_path(
        self, 
        source: str, 
        filename: str,
        create_dirs: bool = True
    ) -> Path:
        """
        获取PDF存储路径（按数据源和年月分类）
        
        Args:
            source: 数据源 ('pubmed', 'europepmc', 'trials')
            filename: 文件名
            create_dirs: 是否自动创建目录
            
        Returns:
            完整的文件路径
        """
        # 按年/月分类
        now = datetime.now()
        year = now.strftime("%Y")
        month = now.strftime("%m")
        
        # 构建路径：pdfs/source/year/month/filename
        dir_path = self.pdf_dir / source / year / month
        
        if create_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
            
        return dir_path / filename
    
    def get_upload_storage_path(
        self,
        file_hash: str,
        original_filename: str,
        user_id: Optional[int] = None,
        create_dirs: bool = True
    ) -> Path:
        """
        获取用户上传文件的存储路径
        
        Args:
            file_hash: 文件MD5哈希
            original_filename: 原始文件名
            user_id: 用户ID（可选）
            create_dirs: 是否自动创建目录
            
        Returns:
            完整的文件路径
        """
        if settings.use_hash_sharding:
            # 使用MD5前2位分片
            shard = file_hash[:2]
            dir_path = self.upload_dir / "files" / shard
        else:
            # 按日期分类（兼容模式）
            now = datetime.now()
            year = now.strftime("%Y")
            month = now.strftime("%m")
            dir_path = self.upload_dir / year / month
            
            if user_id:
                dir_path = dir_path / f"user_{user_id}"
        
        if create_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # 文件名：hash + 原扩展名
        import os
        file_extension = os.path.splitext(original_filename)[1]
        filename = f"{file_hash}{file_extension}"
        
        return dir_path / filename
    
    def cleanup_old_temp_files(self, days: Optional[int] = None):
        """
        清理过期的临时文件
        
        Args:
            days: 保留天数，默认使用配置
        """
        if days is None:
            days = settings.temp_file_cleanup_days
            
        temp_dir = self.upload_dir / "temp"
        if not temp_dir.exists():
            return
        
        import time
        cutoff_time = time.time() - (days * 86400)
        
        deleted_count = 0
        for file_path in temp_dir.glob("*"):
            if file_path.is_file():
                if file_path.stat().st_mtime < cutoff_time:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                    except Exception as e:
                        print(f"删除临时文件失败 {file_path}: {e}")
        
        if deleted_count > 0:
            print(f"✅ 已清理 {deleted_count} 个过期临时文件")
    
    def get_storage_stats(self) -> dict:
        """
        获取存储统计信息
        
        Returns:
            统计信息字典
        """
        def get_dir_size(path: Path) -> int:
            """计算目录大小"""
            total = 0
            if path.exists():
                for file in path.rglob("*"):
                    if file.is_file():
                        total += file.stat().st_size
            return total
        
        stats = {
            "uploads": {
                "size_bytes": get_dir_size(self.upload_dir),
                "size_mb": get_dir_size(self.upload_dir) / 1024 / 1024
            },
            "pdfs": {
                "size_bytes": get_dir_size(self.pdf_dir),
                "size_mb": get_dir_size(self.pdf_dir) / 1024 / 1024
            }
        }
        
        # 统计各数据源的PDF数量
        pdf_sources = {}
        for source_dir in self.pdf_dir.iterdir():
            if source_dir.is_dir():
                count = len(list(source_dir.rglob("*.pdf")))
                pdf_sources[source_dir.name] = count
        
        stats["pdfs"]["sources"] = pdf_sources
        stats["total_size_mb"] = stats["uploads"]["size_mb"] + stats["pdfs"]["size_mb"]
        
        return stats


# 全局实例
storage_helper = StorageHelper()
