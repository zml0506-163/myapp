import enum

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, Integer, Index, Boolean, Enum, BigInteger, DateTime, func
from datetime import datetime


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pmid: Mapped[str | None] = mapped_column(String(32), index=True, unique=False, nullable=True)
    pmcid: Mapped[str] = mapped_column(String(32), index=True, unique=False)  # 例如 "PMC1234567"
    title: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    pub_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    authors: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pdf_path: Mapped[str] = mapped_column(String(1024))  # 本地存储路径（相对/绝对）
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 文章网页（可选）
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


Index("idx_papers_pubdate", Paper.pub_date)
Index("idx_papers_pmid", Paper.pmid)


class ClinicalTrial(Base):
    """
    临床试验表（ClinicalTrials.gov 数据）
    """
    __tablename__ = "clinical_trials"

    # 主键 ID
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # === 基本信息 ===
    nct_id = mapped_column(String(32), unique=True, index=True, nullable=False)  # ClinicalTrials.gov 唯一编号
    title = mapped_column(Text, nullable=False)                                  # 简短标题
    official_title: Mapped[str | None] = mapped_column(Text, nullable=True)                          # 官方标题

    # === 状态信息 ===
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)                            # 招募状态 (Recruiting, Completed, etc.)
    start_date: Mapped[str | None] = mapped_column(String(32), nullable=True)                        # 开始日期（字符串格式即可）
    completion_date: Mapped[str | None] = mapped_column(String(32), nullable=True)                   # 预计/实际完成日期

    # === 研究设计 ===
    study_type: Mapped[str | None] = mapped_column(String(64), nullable=True)                        # 研究类型 (Interventional, Observational)
    phase: Mapped[str | None] = mapped_column(String(64), nullable=True)                             # 临床阶段 (Phase 1, Phase 2, ...)
    allocation: Mapped[str | None] = mapped_column(String(128), nullable=True)                       # 分配方式（随机、非随机）
    intervention_model: Mapped[str | None] = mapped_column(String(128), nullable=True)               # 干预模型（平行、交叉等）

    # === 疾病/条件 ===
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)                              # 研究疾病或条件（逗号分隔）

    # === 赞助方与地点 ===
    sponsor: Mapped[str | None] = mapped_column(String(256), nullable=True)                          # 主要赞助机构
    locations: Mapped[str | None] = mapped_column(Text, nullable=True)                               # 研究地点（城市+国家）

    # === 其他信息 ===
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)                       # ClinicalTrials.gov 页面链接
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


# 枚举类型
class MessageType(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class Conversation(Base):
    """对话表"""
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class Message(Base):
    """消息表"""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[MessageType] = mapped_column(Enum(MessageType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Attachment(Base):
    """附件表"""
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)