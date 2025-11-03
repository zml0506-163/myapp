from pydantic import BaseModel
from datetime import date


class PaperOut(BaseModel):
    id: int
    pmid: str | None
    pmcid: str
    title: str
    abstract: str | None
    pub_date: date | None
    authors: list | dict | None
    pdf_path: str
    source_url: str | None

    class Config:
        from_attributes = True
