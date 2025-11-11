# 日志系统使用指南

## 概述

本项目使用统一的日志管理系统，类似 Java 的 Logback，提供标准化的日志输出和管理。

## 特性

- ✅ **分级日志**：DEBUG, INFO, WARNING, ERROR, CRITICAL
- ✅ **多输出目标**：控制台 + 文件（按日期自动滚动）
- ✅ **格式化输出**：时间、级别、模块、函数、行号等
- ✅ **环境区分**：开发环境和生产环境不同配置
- ✅ **统一接口**：全局可用的 logger 实例

## 快速开始

### 1. 基本使用

```python
from app.core.logger import get_logger

logger = get_logger(__name__)

# 不同级别的日志
logger.debug("调试信息：用于开发阶段的详细信息")
logger.info("一般信息：记录关键操作和流程")
logger.warning("警告信息：潜在问题但不影响运行")
logger.error("错误信息：发生错误但程序可继续")
logger.critical("严重错误：系统级别的严重问题")
```

### 2. 记录异常

```python
try:
    # 你的代码
    result = risky_operation()
except Exception as e:
    # 自动记录完整堆栈信息
    logger.exception(f"操作失败: {e}")
    # 或者手动记录
    import traceback
    logger.error(f"操作失败: {traceback.format_exc()}")
```

### 3. 结构化日志

```python
# 推荐：使用 f-string 格式化
logger.info(f"用户 {user_id} 上传文件: {filename} ({file_size}字节)")

# 推荐：记录关键业务数据
logger.info(f"订单创建成功 | order_id={order_id} | user_id={user_id} | amount={amount}")
```

## 日志级别说明

| 级别 | 使用场景 | 示例 |
|------|---------|------|
| **DEBUG** | 详细的调试信息，仅开发环境使用 | `logger.debug(f"处理参数: {params}")` |
| **INFO** | 关键操作和流程记录 | `logger.info("用户登录成功")` |
| **WARNING** | 潜在问题，不影响运行 | `logger.warning("缓存未命中，使用数据库查询")` |
| **ERROR** | 错误信息，需要关注 | `logger.error("文件上传失败")` |
| **CRITICAL** | 严重错误，系统级问题 | `logger.critical("数据库连接失败")` |

## 配置说明

通过 `.env` 文件配置（参考 `.env.example`）：

```bash
# 日志级别（生产环境建议 INFO 或 WARNING）
LOG_LEVEL=INFO

# 日志文件目录
LOG_DIR=./logs

# 是否输出到控制台（开发: true, 生产: false）
LOG_CONSOLE=true

# 是否输出到文件（生产环境必须: true）
LOG_FILE=true

# 控制台彩色输出（可选）
LOG_COLOR=false
```

## 日志文件管理

### 文件结构

```
logs/
├── app.log              # 所有级别的日志
├── app.log.2025-01-10   # 按天滚动的历史日志
├── error.log            # 仅 ERROR 及以上级别
└── error.log.2025-01-10 # 错误日志历史
```

### 自动清理

- `app.log`: 保留 30 天
- `error.log`: 保留 90 天
- 每天午夜自动滚动

## 最佳实践

### ✅ 推荐做法

```python
# 1. 模块级别的 logger
from app.core.logger import get_logger
logger = get_logger(__name__)

# 2. 记录关键业务操作
logger.info(f"文件上传成功: {filename} (file_id: {file_id})")

# 3. 使用异常记录
try:
    process_file()
except Exception as e:
    logger.exception("文件处理失败")  # 自动包含堆栈信息

# 4. 结构化日志（便于后续分析）
logger.info(f"支付成功 | order_id={order_id} | user_id={user_id} | amount={amount}")
```

### ❌ 不推荐做法

```python
# 1. 不要使用 print（难以管理和追踪）
print("这是一条日志")  # ❌

# 2. 不要在生产环境使用 DEBUG 级别
logger.debug("详细的调试信息")  # ❌ 生产环境会产生大量日志

# 3. 不要记录敏感信息
logger.info(f"用户密码: {password}")  # ❌ 安全风险
logger.info(f"API密钥: {api_key}")    # ❌ 安全风险

# 4. 避免无意义的日志
logger.info("进入函数")  # ❌ 过于冗余
logger.info("退出函数")  # ❌ 过于冗余
```

## 生产环境配置建议

```bash
# .env (生产环境)
LOG_LEVEL=WARNING        # 只记录警告及以上级别
LOG_CONSOLE=false        # 不输出到控制台，减少性能开销
LOG_FILE=true            # 必须写入文件
LOG_DIR=/var/log/pubmed  # 使用专门的日志目录
```

## 日志格式示例

```
2025-01-10 15:30:45 | INFO     | app.api.v1.upload:92 | upload_file | 文件上传成功: test.pdf (file_id: abc123)
2025-01-10 15:30:46 | WARNING  | app.services.file_service:145 | verify_file_id | 缓存失效，重新上传
2025-01-10 15:30:47 | ERROR    | app.api.v1.chat:331 | chat_stream | 聊天错误: Connection timeout
```

格式说明：`时间 | 级别 | 模块:行号 | 函数名 | 消息内容`

## 常见问题

### Q: 如何查看实时日志？

```bash
# Linux/Mac
tail -f logs/app.log

# Windows PowerShell
Get-Content logs/app.log -Wait -Tail 50
```

### Q: 如何搜索特定错误？

```bash
# Linux/Mac
grep "ERROR" logs/app.log
grep "文件上传" logs/app.log

# Windows PowerShell
Select-String "ERROR" logs/app.log
```

### Q: 日志文件太大怎么办？

系统自动按天滚动，可调整 `logger.py` 中的 `backupCount` 参数：

```python
# 修改保留天数
all_handler = TimedRotatingFileHandler(
    ...
    backupCount=7,  # 改为保留7天
)
```

## 迁移指南

将现有的 `print` 替换为 `logger`：

```python
# 旧代码
print(f"✅ 文件已保存: {filename}")
print(f"❌ 上传失败: {error}")

# 新代码
from app.core.logger import get_logger
logger = get_logger(__name__)

logger.info(f"文件已保存: {filename}")
logger.error(f"上传失败: {error}")
```

**批量替换建议**：
- `print(f"✅ ...") → logger.info(...)`
- `print(f"❌ ...") → logger.error(...)`
- `print(f"⚠️ ...") → logger.warning(...)`
