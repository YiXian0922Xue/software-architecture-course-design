from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    description: str = ""
    created_at: str = Field(default_factory=now_iso)


class Resource(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: str
    name: str
    kind: Literal["material", "template", "image"]
    media_type: str = "application/octet-stream"
    path: str
    extracted_text: str = ""
    error: str = ""
    created_at: str = Field(default_factory=now_iso)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict] = []


class ReportRequest(BaseModel):
    format: Literal["latex"] = "latex"
    instructions: str = Field(default="", max_length=4000)
    image_instructions: str = Field(default="", max_length=4000)
    custom_prompt: str = Field(default="", max_length=8000)


class FigurePlacement(BaseModel):
    image_id: str
    caption: str = Field(min_length=1, max_length=300)


class GeneratedSection(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content_markdown: str = Field(default="", max_length=30000)
    figures: list[FigurePlacement] = Field(default_factory=list)


class GeneratedReport(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    sections: list[GeneratedSection] = Field(min_length=1)


class ReportRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: str
    format: Literal["latex"]
    path: str
    created_at: str = Field(default_factory=now_iso)
