"""대표 기사별 P9 추출과 지식 그래프 조립 유스케이스."""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import uuid4

from pydantic import ValidationError

from core.errors import (
    GraphExtractionError,
    InsufficientEventsError,
    IssueNotFoundError,
    LLMOutputValidationError,
)
from core.models import Article, ArticleGraph, ArticleGraphExtraction, GraphProgress, IssueEvent
from core.ports import Repository, StructuredGenerator

GraphProgressSink = Callable[[GraphProgress], None]
RunIdFactory = Callable[[], str]

logger = logging.getLogger("news_tls_agent.graph")


def _new_run_id() -> str:
    return str(uuid4())


def _root_error(exc: Exception) -> Exception:
    current = exc
    while isinstance(current.__cause__, Exception):
        current = current.__cause__
    return current


class KnowledgeGraphService:
    """미추출 대표 기사만 처리하고 저장된 기사별 그래프를 반환한다."""

    def __init__(
        self,
        repository: Repository,
        generator: StructuredGenerator,
        *,
        progress_sink: GraphProgressSink | None = None,
        run_id_factory: RunIdFactory = _new_run_id,
    ) -> None:
        self._repository = repository
        self._generator = generator
        self._progress_sink = progress_sink
        self._run_id_factory = run_id_factory

    def build(self, issue_id: int) -> tuple[ArticleGraph, ...]:
        run_id = self._run_id_factory()
        model_name = getattr(self._generator, "model_name", type(self._generator).__name__)
        logger.info(
            "graph started: run_id=%s issue_id=%s model=%s response_type=%s",
            run_id,
            issue_id,
            model_name,
            ArticleGraphExtraction.__name__,
            extra={
                "event_name": "graph.started",
                "run_id": run_id,
                "issue_id": issue_id,
                "model_name": model_name,
                "response_type": ArticleGraphExtraction.__name__,
            },
        )
        issue = self._repository.get_issue(issue_id)
        if issue is None:
            raise IssueNotFoundError(f"이슈를 찾을 수 없습니다: {issue_id}")
        if len(issue.events) <= 1:
            raise InsufficientEventsError("이벤트가 1건 이하여서 그래프를 만들 수 없습니다")

        representatives = _unique_representatives(issue.events)
        pending = [article for article in representatives if article.entities_extracted_at is None]
        for index, article in enumerate(pending):
            self._report(len(pending) - index)
            if not article.content or not article.content.strip():
                raise GraphExtractionError(f"기사 본문이 비어 있습니다: {article.article_id}")
            try:
                extraction = self._extract(article, run_id)
            except Exception as exc:
                output_error = exc if isinstance(exc, LLMOutputValidationError) else None
                root_error = output_error or _root_error(exc)
                validation_error = (
                    output_error.validation_error if output_error is not None else str(root_error)
                )
                invalid_endpoints = (
                    output_error.invalid_endpoints if output_error is not None else ()
                )
                logger.exception(
                    "graph extraction failed: run_id=%s article_id=%s response_type=%s "
                    "error_type=%s validation_error=%s invalid_endpoints=%s",
                    run_id,
                    article.article_id,
                    ArticleGraphExtraction.__name__,
                    type(root_error).__name__,
                    validation_error,
                    invalid_endpoints,
                    extra={
                        "event_name": "graph.extraction.failed",
                        "run_id": run_id,
                        "article_id": article.article_id,
                        "response_type": ArticleGraphExtraction.__name__,
                        "error_type": type(root_error).__name__,
                        "validation_error": validation_error,
                        "invalid_endpoints": invalid_endpoints,
                    },
                )
                raise
            try:
                self._repository.replace_article_graph(article.article_id, extraction)
            except Exception as exc:
                logger.exception(
                    "graph save failed: run_id=%s article_id=%s error_type=%s",
                    run_id,
                    article.article_id,
                    type(exc).__name__,
                    extra={
                        "event_name": "graph.save.failed",
                        "run_id": run_id,
                        "article_id": article.article_id,
                        "error_type": type(exc).__name__,
                    },
                )
                raise GraphExtractionError(
                    f"기사 그래프를 저장하지 못했습니다: {article.article_id}"
                ) from exc

        graphs: list[ArticleGraph] = []
        for article in representatives:
            graph = self._repository.get_article_graph(article.article_id)
            if graph is None:
                raise GraphExtractionError(
                    f"저장된 기사 그래프를 읽지 못했습니다: {article.article_id}"
                )
            graphs.append(graph)
        return tuple(graphs)

    def _extract(self, article: Article, run_id: str) -> ArticleGraphExtraction:
        try:
            return self._generator.generate(_extraction_prompt(article), ArticleGraphExtraction)
        except LLMOutputValidationError as first_error:
            logger.warning(
                "graph correction requested: run_id=%s article_id=%s response_type=%s "
                "invalid_endpoints=%s",
                run_id,
                article.article_id,
                first_error.response_type,
                first_error.invalid_endpoints,
                extra={
                    "event_name": "graph.extraction.correction_requested",
                    "run_id": run_id,
                    "article_id": article.article_id,
                    "response_type": first_error.response_type,
                    "invalid_endpoints": first_error.invalid_endpoints,
                },
            )
            try:
                return self._generator.generate(
                    _correction_prompt(article, first_error),
                    ArticleGraphExtraction,
                )
            except LLMOutputValidationError as retry_error:
                try:
                    extraction, discarded = ArticleGraphExtraction.discard_invalid_relations(
                        retry_error.raw_output
                    )
                except (TypeError, ValueError, ValidationError):
                    raise retry_error from None
                discarded_endpoints = tuple(
                    (relation.source, relation.target) for relation in discarded
                )
                logger.warning(
                    "graph invalid relations discarded: run_id=%s article_id=%s "
                    "response_type=%s invalid_endpoints=%s",
                    run_id,
                    article.article_id,
                    retry_error.response_type,
                    discarded_endpoints,
                    extra={
                        "event_name": "graph.extraction.invalid_relations_discarded",
                        "run_id": run_id,
                        "article_id": article.article_id,
                        "response_type": retry_error.response_type,
                        "invalid_endpoints": discarded_endpoints,
                    },
                )
                return extraction

    def _report(self, remaining: int) -> None:
        if self._progress_sink is not None:
            self._progress_sink(GraphProgress(remaining=remaining))


def _unique_representatives(events: tuple[IssueEvent, ...]) -> tuple[Article, ...]:
    representatives: list[Article] = []
    seen: set[int] = set()
    for event in events:
        representative = event.representative_article
        if representative.article_id in seen:
            continue
        seen.add(representative.article_id)
        representatives.append(representative)
    return tuple(representatives)


def _extraction_prompt(article: Article) -> str:
    return f"""다음 뉴스 기사 한 건에 실제로 서술된 엔티티와 관계만 추출하세요.

규칙:
- 인물·기관·장소·사건의 표기를 기사에 등장한 그대로 사용합니다.
- 정식 명칭으로 바꾸거나 서로 다른 호칭을 병합하지 않습니다.
- 관계의 source와 target은 반드시 entities에 같은 표기로 포함합니다.
- 일반 상식으로 관계를 보충하지 않습니다.
- 관계가 없어도 확인된 엔티티는 반환할 수 있습니다.

ARTICLE_ID: {article.article_id}
TITLE: {article.title}
CONTENT:
{article.content}
"""


def _correction_prompt(article: Article, error: LLMOutputValidationError) -> str:
    endpoints = ", ".join(f"{source!r}->{target!r}" for source, target in error.invalid_endpoints)
    return f"""{_extraction_prompt(article)}

직전 {error.response_type} 출력은 구조 검증에 실패했습니다.
검증 오류: {error.validation_error}
잘못된 관계 끝점: {endpoints or "확인되지 않음"}
entities에 같은 표기로 존재하는 source와 target만 사용해 전체 출력을 한 번 수정하세요.
"""
