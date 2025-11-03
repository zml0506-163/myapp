from datetime import datetime
from operator import or_
from typing import Optional, Tuple, List, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, and_
from app.models import Paper, ClinicalTrial


async def upsert_paper(db: AsyncSession, *, pmid: str | None, pmcid: str, title: str,
                       source_type: str,
                       abstract: str | None, pub_date, authors, pdf_path: str,
                       source_url: str | None):

    source_condition = Paper.source_type == source_type
    if pmid is not None:
        # 如果 pmid 存在，用 pmid + source 条件查询
        query = select(Paper).where(and_(Paper.pmid == pmid, source_condition))
    else:
        # 如果 pmid 是 None，用 pmcid + source 条件查询（需确保 pmcid 不为 None）
        query = select(Paper).where(and_(Paper.pmcid == pmcid, source_condition))
    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        existing.pmid = pmid or existing.pmid
        existing.pmcid = pmcid or existing.pmcid
        existing.title = title
        existing.source_type = source_type
        existing.abstract = abstract
        existing.pub_date = pub_date
        existing.authors = authors
        existing.pdf_path = pdf_path
        existing.source_url = source_url
    else:
        existing = Paper(
            pmid=pmid, pmcid=pmcid, title=title, source_type=source_type,abstract=abstract,
            pub_date=pub_date, authors=authors, pdf_path=pdf_path, source_url=source_url
        )
        db.add(existing)

    # 关键：提交事务
    await db.commit()

    # 刷新对象以获取数据库生成的属性（如ID、默认值等）
    await db.refresh(existing)

    return existing


async def list_papers(
        db: AsyncSession,
        limit: int = 10,
        offset: int = 0,
        pmid: Optional[str] = None,
        title: Optional[str] = None,
        author: Optional[str] = None
) -> Tuple[List[Paper], int]:
    """
    分页查询文献列表，支持多条件搜索
    返回：(文献列表, 总条数)
    """
    # 构建基础查询
    query = select(Paper).order_by(desc(Paper.id))

    # 添加搜索条件
    filters = []
    if pmid:
        filters.append(Paper.pmid.ilike(f"%{pmid}%"))
    if title:
        filters.append(Paper.title.ilike(f"%{title}%"))
    if author and author.strip():
        filters.append(Paper.authors.ilike(f"%{author}%"))

    # 应用过滤条件
    if filters:
        query = query.where(*filters)

    # 计算总数
    total_query = select(Paper.id).where(*filters) if filters else select(Paper.id)
    total_result = await db.execute(total_query)
    total = len(total_result.scalars().all())

    # 应用分页并执行查询
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    papers = result.scalars().all()

    return papers, total


async def upsert_clinical_trial(
        db: AsyncSession,
        *,
        nct_id: str,
        title: str,
        official_title: str | None = None,
        status: str | None = None,
        start_date: str | None = None,
        completion_date: str | None = None,
        study_type: str | None = None,
        phase: str | None = None,
        allocation: str | None = None,
        intervention_model: str | None = None,
        conditions: str | None = None,
        sponsor: str | None = None,
        locations: str | None = None,
        source_url: str | None = None
):
    """
    异步 Upsert：如果存在则更新，否则插入新的临床试验记录
    """

    # 查找是否已存在
    result = await db.execute(select(ClinicalTrial).where(ClinicalTrial.nct_id == nct_id))
    existing = result.scalar_one_or_none()

    now = datetime.utcnow()

    if existing:
        # === 已存在则更新 ===
        existing.title = title
        existing.official_title = official_title or existing.official_title
        existing.status = status or existing.status
        existing.start_date = start_date or existing.start_date
        existing.completion_date = completion_date or existing.completion_date
        existing.study_type = study_type or existing.study_type
        existing.phase = phase or existing.phase
        existing.allocation = allocation or existing.allocation
        existing.intervention_model = intervention_model or existing.intervention_model
        existing.conditions = conditions or existing.conditions
        existing.sponsor = sponsor or existing.sponsor
        existing.locations = locations or existing.locations
        existing.source_url = source_url or existing.source_url
        existing.updated_at = now
    else:
        # === 不存在则新增 ===
        existing = ClinicalTrial(
            nct_id=nct_id,
            title=title,
            official_title=official_title,
            status=status,
            start_date=start_date,
            completion_date=completion_date,
            study_type=study_type,
            phase=phase,
            allocation=allocation,
            intervention_model=intervention_model,
            conditions=conditions,
            sponsor=sponsor,
            locations=locations,
            source_url=source_url,
            created_at=now,
            updated_at=now
        )
        db.add(existing)

    # 提交事务并刷新
    await db.commit()
    await db.refresh(existing)
    return existing


# 允许的状态列表
ALLOWED_STATUSES = {
    "ACTIVE_NOT_RECRUITING", "COMPLETED", "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING", "RECRUITING", "SUSPENDED", "TERMINATED",
    "WITHDRAWN", "AVAILABLE", "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE", "APPROVED_FOR_MARKETING",
    "WITHHELD", "UNKNOWN"
}

async def list_trials_with_pagination(
        db: AsyncSession,
        page_size: int,
        offset: int,
        nct_id: Optional[str] = None,
        condition: Optional[str] = None,
        status: Optional[str] = None
):
    """
    分页查询临床试验列表，支持筛选条件

    返回：(查询结果列表, 总记录数)
    """
    # 基础查询
    query = select(ClinicalTrial)

    # 应用筛选条件
    # if nct_id:
    #     query = query.filter(ClinicalTrial.nct_id.ilike(f"%{nct_id}%"))
    if nct_id:
        nct_ids = [item.strip() for item in nct_id.split(',') if item.strip()]
        if nct_ids:
            # 初始化条件为第一个元素
            combined_condition = ClinicalTrial.nct_id.ilike(f"%{nct_ids[0]}%")
            # 依次用 OR 拼接剩余条件
            for nct in nct_ids[1:]:
                combined_condition = combined_condition | ClinicalTrial.nct_id.ilike(f"%{nct}%")
            query = query.filter(combined_condition)

    if condition and condition.strip():
        query = query.filter(ClinicalTrial.conditions.ilike(f"%{condition.strip()}%"))

    if status and status in ALLOWED_STATUSES:
        query = query.filter(ClinicalTrial.status == status)

    # 获取总记录数
    total_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(total_query)
    total = total_result.scalar()

    # 应用分页并执行查询
    query = query.order_by(ClinicalTrial.start_date.desc()).limit(page_size).offset(offset)
    result = await db.execute(query)
    trials = result.scalars().all()

    return trials, total
