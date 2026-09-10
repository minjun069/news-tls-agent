"""데이터 계층의 도메인 입출력 스키마."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

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


class ArticleSearchRequest(DomainModel):
    """P3가 선택한 검색 방식과 방식별 입력을 보존한 요청."""

    method: SearchMethod
    options: SearchOptions
    keyword_terms: tuple[str, ...] = ()
    keyword_operator: KeywordOperator = KeywordOperator.OR
    semantic_text: str | None = None

    @model_validator(mode="after")
    def validate_method_inputs(self) -> Self:
        normalized_terms = tuple(
            dict.fromkeys(term.strip() for term in self.keyword_terms if term.strip())
        )
        semantic_text = self.semantic_text.strip() if self.semantic_text else None
        if self.method in {SearchMethod.KEYWORD, SearchMethod.HYBRID} and not normalized_terms:
            raise ValueError("keyword·hybrid 검색에는 keyword_terms가 필요합니다")
        if self.method in {SearchMethod.SEMANTIC, SearchMethod.HYBRID} and not semantic_text:
            raise ValueError("semantic·hybrid 검색에는 semantic_text가 필요합니다")
        object.__setattr__(self, "keyword_terms", normalized_terms)
        object.__setattr__(self, "semantic_text", semantic_text)
        return self


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


class IssueSummary(DomainModel):
    """목록 조회에 필요한 이슈 요약과 이벤트 수."""

    issue_id: int
    topic: str
    title: str | None
    generated_at: datetime
    event_count: int = Field(ge=0)


class IssueCitation(DomainModel):
    issue_id: int
    topic: str
    event_id: int
    event_date: date
    event_title: str


class ExtractedEntity(DomainModel):
    """P9가 기사 표면형 그대로 반환하는 저장 전 엔티티."""

    name: str = Field(min_length=1, max_length=300)
    entity_type: str = Field(min_length=1, max_length=50)

    @field_validator("name", "entity_type")
    @classmethod
    def strip_entity_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("엔티티 표기와 유형은 빈 문자열일 수 없습니다")
        return stripped


class ExtractedRelation(DomainModel):
    """P9 엔티티 이름으로 양 끝점을 지칭하는 저장 전 관계."""

    source: str = Field(min_length=1, max_length=300)
    target: str = Field(min_length=1, max_length=300)
    relation_type: str = Field(min_length=1, max_length=100)

    @field_validator("source", "target", "relation_type")
    @classmethod
    def strip_relation_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("관계의 주체·대상·유형은 빈 문자열일 수 없습니다")
        return stripped


class ArticleGraphExtraction(DomainModel):
    """기사 한 건에서 추출한 P9 구조화 출력."""

    entities: tuple[ExtractedEntity, ...] = ()
    relations: tuple[ExtractedRelation, ...] = ()

    @model_validator(mode="after")
    def validate_relation_endpoints(self) -> Self:
        names = [entity.name for entity in self.entities]
        if len(names) != len(set(names)):
            raise ValueError("한 기사 안에서 엔티티 표기는 중복될 수 없습니다")
        available = set(names)
        invalid = tuple(
            relation
            for relation in self.relations
            if relation.source not in available or relation.target not in available
        )
        if invalid:
            endpoints = ", ".join(
                f"{relation.source!r}->{relation.target!r}" for relation in invalid
            )
            raise ValueError(f"관계의 주체와 대상은 entities에 있어야 합니다: {endpoints}")
        return self

    @classmethod
    def discard_invalid_relations(
        cls,
        payload: object,
    ) -> tuple[Self, tuple[ExtractedRelation, ...]]:
        """끝점만 잘못된 관계를 제외하고 나머지 구조를 다시 검증한다."""
        if not isinstance(payload, Mapping):
            raise TypeError("그래프 출력 원본이 객체가 아닙니다")
        entities = tuple(
            ExtractedEntity.model_validate(item) for item in payload.get("entities", ())
        )
        relations = tuple(
            ExtractedRelation.model_validate(item) for item in payload.get("relations", ())
        )
        available = {entity.name for entity in entities}
        discarded = tuple(
            relation
            for relation in relations
            if relation.source not in available or relation.target not in available
        )
        if not discarded:
            raise ValueError("제외할 잘못된 관계 끝점이 없습니다")
        valid_relations = tuple(relation for relation in relations if relation not in discarded)
        return cls(entities=entities, relations=valid_relations), discarded


class GraphNode(DomainModel):
    id: int
    name: str
    type: str


class GraphEdge(DomainModel):
    id: int
    source: int
    target: int
    type: str


class ArticleGraph(DomainModel):
    """NFR-16에 따라 기사 귀속을 보존하는 한 개의 그래프."""

    article_id: int
    article_title: str
    article_service_date: date
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()


class GraphProgress(DomainModel):
    remaining: int = Field(ge=0)


class ExportFormat(StrEnum):
    PDF = "pdf"
    NOTION = "notion"


class NotionPage(DomainModel):
    page_id: str
    url: str


class PipelineStage(StrEnum):
    """NFR-14 로그와 진행 알림에 쓰는 S5 단계."""

    INTERPRET_INTENT = "intent"
    CLARIFY = "clarify"
    BUILD_HYPOTHETICAL_TIMELINE = "hypothetical"
    GENERATE_SEARCH_QUERY = "search"
    SELECT_ARTICLES = "select"
    EXTRACT_RELATED_EVENTS = "expand"
    REVIEW_SUFFICIENCY = "sufficiency"
    GENERATE_HYPOTHESES = "hypothesize"
    MERGE_TIMELINE = "merge"
    SAVE_ISSUE = "save"
    CACHED = "cached"


class TerminationReason(StrEnum):
    """타임라인 수집 루프의 네 종료 조건과 캐시 재사용."""

    SUFFICIENCY_PASSED = "sufficiency_passed"
    CONVERGED = "converged"
    DEPTH_LIMIT = "depth_limit"
    ROUND_LIMIT = "round_limit"
    CACHED = "cached"


class GenerationStatus(StrEnum):
    """호출자가 다음 행동을 결정할 수 있는 생성 결과."""

    COMPLETED = "completed"
    REUSED = "reused"
    NEEDS_CLARIFICATION = "needs_clarification"
    NO_ARTICLES = "no_articles"


class PipelineProgress(DomainModel):
    """S6의 SSE와 CLI가 공유할 단계별 진행 값."""

    round_number: int = Field(ge=0)
    stage: PipelineStage
    selected_article_count: int = Field(ge=0)
    termination: TerminationReason | None = None


class IntentInterpretation(DomainModel):
    intent: str = Field(min_length=1)
    user_specified_date: bool = False
    needs_clarification: bool
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_clarification(self) -> Self:
        question = self.clarification_question.strip() if self.clarification_question else None
        if self.needs_clarification and not question:
            raise ValueError("되묻기가 필요하면 clarification_question이 있어야 합니다")
        object.__setattr__(self, "clarification_question", question)
        return self


class HypotheticalEvent(DomainModel):
    expected_date: date
    description: str = Field(min_length=1)


class HypotheticalTimeline(DomainModel):
    date_from: date
    date_to: date
    events: tuple[HypotheticalEvent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.date_from > self.date_to:
            raise ValueError("가상 타임라인 시작일은 종료일보다 늦을 수 없습니다")
        return self


class SearchQueryDraft(DomainModel):
    """P3 구조화 출력. 이유는 실행 로그에 남길 수 있도록 보존한다."""

    method: SearchMethod
    reason: str = Field(min_length=1)
    keyword_terms: tuple[str, ...] = ()
    keyword_operator: KeywordOperator = KeywordOperator.OR
    semantic_text: str | None = None
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def validate_query_inputs(self) -> Self:
        normalized_terms = tuple(
            dict.fromkeys(term.strip() for term in self.keyword_terms if term.strip())
        )
        semantic_text = self.semantic_text.strip() if self.semantic_text else None
        if self.date_from > self.date_to:
            raise ValueError("검색 시작일은 종료일보다 늦을 수 없습니다")
        if self.method in {SearchMethod.KEYWORD, SearchMethod.HYBRID} and not normalized_terms:
            raise ValueError("keyword·hybrid 검색에는 keyword_terms가 필요합니다")
        if self.method in {SearchMethod.SEMANTIC, SearchMethod.HYBRID} and not semantic_text:
            raise ValueError("semantic·hybrid 검색에는 semantic_text가 필요합니다")
        object.__setattr__(self, "keyword_terms", normalized_terms)
        object.__setattr__(self, "semantic_text", semantic_text)
        return self

    def to_search_request(self, *, top_k: int) -> ArticleSearchRequest:
        return ArticleSearchRequest(
            method=self.method,
            options=SearchOptions(
                top_k=top_k,
                date_from=self.date_from,
                date_to=self.date_to,
            ),
            keyword_terms=self.keyword_terms,
            keyword_operator=self.keyword_operator,
            semantic_text=self.semantic_text,
        )


class SelectedArticle(DomainModel):
    article_id: int
    event_date: date
    event_summary: str = Field(min_length=1)
    relevance_score: float = Field(ge=0, le=1)


class RejectedArticle(DomainModel):
    article_id: int
    reason: str = Field(min_length=1)


class ArticleSelection(DomainModel):
    selected: tuple[SelectedArticle, ...] = ()
    rejected: tuple[RejectedArticle, ...] = ()


class RelatedEvent(DomainModel):
    event_date: date
    description: str = Field(min_length=1)
    source_article_id: int


class RelatedEvents(DomainModel):
    events: tuple[RelatedEvent, ...] = ()


class SufficiencyReview(DomainModel):
    is_sufficient: bool
    gaps: tuple[str, ...] = ()
    updated_date_from: date | None = None
    updated_date_to: date | None = None

    @model_validator(mode="after")
    def validate_updated_period(self) -> Self:
        dates = (self.updated_date_from, self.updated_date_to)
        if (dates[0] is None) is not (dates[1] is None):
            raise ValueError("갱신 기간은 시작일과 종료일을 함께 반환해야 합니다")
        if dates[0] is not None and dates[1] is not None and dates[0] > dates[1]:
            raise ValueError("갱신 시작일은 종료일보다 늦을 수 없습니다")
        return self


class AdditionalHypotheses(DomainModel):
    events: tuple[HypotheticalEvent, ...] = ()


class MergedTimelineEvent(DomainModel):
    event_date: date
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    article_ids: tuple[int, ...] = Field(min_length=1)

    @field_validator("article_ids")
    @classmethod
    def deduplicate_article_ids(cls, article_ids: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(dict.fromkeys(article_ids))


class MergedTimeline(DomainModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    events: tuple[MergedTimelineEvent, ...] = ()


class TimelineGenerationResult(DomainModel):
    status: GenerationStatus
    issue_id: int | None = None
    clarification_question: str | None = None
    termination: TerminationReason | None = None
    rounds: int = Field(default=0, ge=0)
    selected_article_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        if self.status in {GenerationStatus.COMPLETED, GenerationStatus.REUSED}:
            if self.issue_id is None:
                raise ValueError("완료·재사용 결과에는 issue_id가 필요합니다")
        if self.status is GenerationStatus.NEEDS_CLARIFICATION:
            if not self.clarification_question:
                raise ValueError("되묻기 결과에는 질문이 필요합니다")
        return self


class ChatMessage(DomainModel):
    """클라이언트가 매 요청에 다시 보내는 서버 비저장 대화 이력."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatSource(StrEnum):
    """CHAT-004가 화면에 노출하는 문단 단위 출처."""

    ARTICLE = "article"
    GENERAL = "general"


class ChatToolProgress(DomainModel):
    event: Literal["tool"] = "tool"
    name: str
    label: str


class ChatToken(DomainModel):
    event: Literal["token"] = "token"
    text: str
    source: ChatSource


class ChatDone(DomainModel):
    event: Literal["done"] = "done"
    article_ids: tuple[int, ...] = ()
    exports: tuple[dict[str, object], ...] = ()


ChatEvent = ChatToolProgress | ChatToken | ChatDone
