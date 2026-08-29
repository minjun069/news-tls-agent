"""데이터 계층의 도메인 입출력 스키마."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DomainModel(BaseModel):
    """저장소 경계에서 값이 바뀌지 않는 공통 도메인 모델."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


class SearchMethod(StrEnum):
    """NFR-04가 노출하는 세 검색 방식."""

    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class KeywordOperator(StrEnum):
    """키워드 묶음의 포함 조건."""

    OR = "or"
    AND = "and"


class SearchOptions(DomainModel):
    """모든 검색기가 동일하게 적용하는 개수·기간 제약."""

    top_k: int = Field(default=5, ge=1, le=100)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.date_from is not None and self.date_to is not None:
            if self.date_from > self.date_to:
                raise ValueError("date_from은 date_to보다 늦을 수 없습니다")
        return self


class KeywordQuery(SearchOptions):
    """BM25 검색어와 OR·AND 결합 방식."""

    terms: tuple[str, ...] = Field(min_length=1)
    operator: KeywordOperator = KeywordOperator.OR

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, terms: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for term in terms:
            stripped = term.strip()
            if not stripped:
                raise ValueError("검색어는 빈 문자열일 수 없습니다")
            if stripped not in normalized:
                normalized.append(stripped)
        return tuple(normalized)


class SemanticQuery(SearchOptions):
    """임베딩할 의미 검색 문장."""

    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            raise ValueError("검색 문장은 빈 문자열일 수 없습니다")
        return stripped


class SearchHit(DomainModel):
    """저장소가 반환하는 기사 ID와 방식별 원점수."""

    article_id: int
    score: float


class SearchResult(DomainModel):
    """선택한 방식과 순위가 보존된 검색 결과."""

    method: SearchMethod
    hits: tuple[SearchHit, ...]


class VectorPoint(DomainModel):
    """검색 인덱스 한 포인트의 dense 벡터, BM25 입력 텍스트, 메타데이터."""

    article_id: int
    vector: tuple[float, ...] | None = Field(default=None, min_length=1)
    search_text: str = Field(min_length=1)
    service_date: date
    title: str = Field(min_length=1, max_length=500)
    category_middle: str | None = Field(default=None, max_length=100)

    @field_validator("search_text")
    @classmethod
    def normalize_search_text(cls, search_text: str) -> str:
        stripped = search_text.strip()
        if not stripped:
            raise ValueError("BM25 입력 텍스트는 빈 문자열일 수 없습니다")
        return stripped


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
