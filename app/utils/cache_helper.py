"""
缓存助手 - 支持 Redis 和本地内存两种模式

app/utils/cache_helper.py

功能说明：
1. 支持 Redis 缓存和本地内存缓存两种模式
2. 通过配置文件动态切换缓存后端
3. Redis 连接失败时自动降级为本地缓存
4. 提供 JSON 序列化/反序列化工具方法

使用示例：
    # 基本缓存操作
    await set_cache("key", "value", expire=3600)
    value = await get_cache("key")
    await delete_cache("key")
    
    # JSON 缓存
    await set_json_cache("user:1", {"name": "Alice", "age": 25}, expire=1800)
    user_data = await get_json_cache("user:1")
    
    # 清理匹配的缓存
    await clear_cache_pattern("user:*")
"""
import json
from typing import Optional, Any
from collections import defaultdict

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

# ============================================
# 本地内存缓存
# ============================================
_memory_cache: dict[str, str] = defaultdict(str)

# ============================================
# Redis 客户端（懒加载）
# ============================================
_redis_client: Optional[Any] = None


# ============================================
# Redis 客户端管理
# ============================================

def get_redis_client() -> Optional[Any]:
    """
    获取 Redis 客户端（懒加载）
    
    Returns:
        Redis 客户端实例，如果未启用或连接失败则返回 None
        
    说明：
        - 首次调用时尝试建立 Redis 连接
        - 连接失败会记录错误日志并自动降级到本地缓存
        - 后续调用直接返回缓存的客户端实例
    """
    global _redis_client
    
    # 检查是否启用 Redis 缓存
    if not settings.use_redis_cache:
        return None
    
    # 已有连接则直接返回
    if _redis_client is not None:
        return _redis_client
    
    # 尝试建立 Redis 连接
    try:
        import redis  # type: ignore
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True  # 自动将字节解码为字符串
        )
        # 测试连接
        _redis_client.ping()  # type: ignore
        logger.info(f"Redis 连接成功: {settings.redis_url}")
        return _redis_client
    except Exception as e:
        logger.error(f"Redis 连接失败: {e}，降级为本地内存缓存")
        _redis_client = None
        return None


# ============================================
# 缓存基础操作
# ============================================


async def set_cache(key: str, value: str, expire: Optional[int] = None) -> bool:
    """
    设置缓存
    
    Args:
        key: 缓存键
        value: 缓存值（字符串）
        expire: 过期时间（秒），为 None 则使用默认配置
        
    Returns:
        bool: 操作是否成功
    """
    # 使用默认过期时间
    if expire is None:
        expire = settings.redis_cache_expire
    
    # 尝试使用 Redis
    if settings.use_redis_cache:
        client = get_redis_client()
        if client:
            try:
                client.set(key, value, ex=expire)
                return True
            except Exception as e:
                logger.error(f"Redis set 失败: {e}")
    
    # 降级到本地内存
    _memory_cache[key] = value
    return True


async def get_cache(key: str) -> Optional[str]:
    """
    获取缓存
    
    Args:
        key: 缓存键
        
    Returns:
        缓存值，不存在则返回 None
    """
    # 尝试从 Redis 读取
    if settings.use_redis_cache:
        client = get_redis_client()
        if client:
            try:
                return client.get(key)
            except Exception as e:
                logger.error(f"Redis get 失败: {e}")
    
    # 降级到本地内存
    return _memory_cache.get(key)


async def delete_cache(key: str) -> bool:
    """
    删除缓存
    
    Args:
        key: 缓存键
        
    Returns:
        bool: 操作是否成功
    """
    # 尝试从 Redis 删除
    if settings.use_redis_cache:
        client = get_redis_client()
        if client:
            try:
                client.delete(key)
                return True
            except Exception as e:
                logger.error(f"Redis delete 失败: {e}")
    
    # 降级到本地内存
    if key in _memory_cache:
        del _memory_cache[key]
    return True


async def clear_cache_pattern(pattern: str) -> int:
    """
    清除匹配模式的所有缓存
    
    Args:
        pattern: 匹配模式，支持通配符 *，例如 "user:*"
        
    Returns:
        int: 删除的缓存数量
    """
    deleted_count = 0
    
    # 尝试从 Redis 清理
    if settings.use_redis_cache:
        client = get_redis_client()
        if client:
            try:
                keys = client.keys(pattern)
                if keys:
                    deleted_count = client.delete(*keys)
                return deleted_count
            except Exception as e:
                logger.error(f"Redis clear pattern 失败: {e}")
    
    # 降级到本地内存（简单实现：处理 * 通配符）
    prefix = pattern.replace('*', '')
    keys_to_delete = [k for k in _memory_cache.keys() if k.startswith(prefix)]
    for key in keys_to_delete:
        del _memory_cache[key]
        deleted_count += 1
    
    return deleted_count


# ============================================
# JSON 缓存工具方法
# ============================================
async def set_json_cache(key: str, value: Any, expire: Optional[int] = None) -> bool:
    """
    存储 JSON 格式的缓存
    
    Args:
        key: 缓存键
        value: 任意可 JSON 序列化的对象
        expire: 过期时间（秒）
        
    Returns:
        bool: 操作是否成功
    """
    try:
        json_str = json.dumps(value, ensure_ascii=False)
        return await set_cache(key, json_str, expire)
    except (TypeError, ValueError) as e:
        logger.error(f"JSON 序列化失败: {key}, 错误: {e}")
        return False


async def get_json_cache(key: str) -> Optional[Any]:
    """
    获取 JSON 格式的缓存
    
    Args:
        key: 缓存键
        
    Returns:
        反序列化后的对象，失败或不存在则返回 None
    """
    value = await get_cache(key)
    if value:
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {key}, 错误: {e}")
            return None
    return None
