from __future__ import annotations
from typing import List, Optional, AsyncGenerator
from pydantic import BaseModel

class Meta(BaseModel):
    took_ms: Optional[int] = None
    retries: Optional[int] = None

class Paper(BaseModel):
    id: Optional[int] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    title: str
    abstract: Optional[str] = None
    pub_date: Optional[str] = None
    authors: Optional[str] = None
    pdf_path: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None

class Trial(BaseModel):
    nct_id: str
    title: str
    status: Optional[str] = None
    phase: Optional[str] = None
    conditions: Optional[str] = None
    sponsor: Optional[str] = None
    locations: Optional[str] = None
    source_url: Optional[str] = None

class PapersResult(BaseModel):
    papers: List[Paper]
    meta: Optional[Meta] = None

class TrialsResult(BaseModel):
    trials: List[Trial]
    meta: Optional[Meta] = None

class DownloadResult(BaseModel):
    path: str
    bytes: Optional[int] = None
    meta: Optional[Meta] = None

class AnalysisResult(BaseModel):
    analysis: str
    meta: Optional[Meta] = None

class SummaryResult(BaseModel):
    summary: str
    meta: Optional[Meta] = None

class ReportResult(BaseModel):
    final_answer: str
    meta: Optional[Meta] = None
