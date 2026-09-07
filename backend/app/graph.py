"""대표 기사별 P9 추출과 지식 그래프 조립 유스케이스."""

from __future__ import annotations

from collections.abc import Callable

from core.errors import GraphExtractionError, InsufficientEventsError, IssueNotFoundError
from core.models import Article, ArticleGraph, ArticleGraphExtraction, GraphProgress, IssueEvent
from core.ports import Repository, StructuredGenerator

GraphProgressSink = Callable[[GraphProgress], None]


class KnowledgeGraphService:
    """미추출 대표 기사만 처리하고 저장된 기사별 그래프를 반환한다."""

    def __init__(
        self,
        repository: Repository,
        generator: StructuredGenerator,
        *,
        progress_sink: GraphProgressSink | None = None,
    ) -> None:
        self._repository = repository
        self._generator = generator
        self._progress_sink = progress_sink

    def build(self, issue_id: int) -> tuple[ArticleGraph, ...]:
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
            extraction = self._generator.generate(
                _extraction_prompt(article),
                ArticleGraphExtraction,
            )
            try:
                self._repository.replace_article_graph(article.article_id, extraction)
            except Exception as exc:
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
