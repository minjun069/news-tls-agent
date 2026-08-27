"""데이터 계층의 도메인 입출력 스키마."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """저장소 경계에서 값이 바뀌지 않는 공통 도메인 모델."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


class Article(DomainModel):
    article_id: int
    title: str = Field(min_length=1, max_length=500)
    sub_title: str | None = Field(default=None, max_length=500)
    service_date: date
    summary: str | None = None
    content: str | None = None
    url: str | None = Field(default=None, max_length=1000)
    category_large: str | None = Field(default=None, max_length=100)
    category_middle: str | None = Field(default=None, max_length=100)
    category_small: str | None = Field(default=None, max_length=100)
    entities_extracted_at: datetime | None = None


class EventArticleInput(DomainModel):
    article_id: int
    relevance_score: float | None = None


class IssueEventInput(DomainModel):
    event_order: int = Field(ge=0)
    event_date: date
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    articles: tuple[EventArticleInput, ...] = Field(min_length=1)


class IssueCreate(DomainModel):
    topic: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=500)
    summary: str | None = None
    generated_at: datetime
    events: tuple[IssueEventInput, ...] = Field(min_length=1)


class EventArticle(DomainModel):
    article: Article
    relevance_score: float | None = None


class IssueEvent(DomainModel):
    event_id: int
    event_order: int
    event_date: date
    title: str
    summary: str | None
    articles: tuple[EventArticle, ...]
    representative_article: Article


class IssueDetail(DomainModel):
    issue_id: int
    topic: str
    title: str | None
    summary: str | None
    generated_at: datetime
    events: tuple[IssueEvent, ...]


class IssueCitation(DomainModel):
    issue_id: int
    topic: str
    event_id: int
    event_date: date
    event_title: str
