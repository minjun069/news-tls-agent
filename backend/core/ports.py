"""애플리케이션이 요구하는 저장소 계약.

구현 기술(SQLAlchemy, MS-SQL)은 infra에만 있고 상위 계층은 이 타입만 의존한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from core.models import (
    Article,
    IssueCitation,
    IssueCreate,
    IssueDetail,
    KeywordQuery,
    SearchHit,
    SearchOptions,
    VectorPoint,
)


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """적재할 문서들을 같은 차원의 dense 벡터로 변환한다."""
        ...

    def embed_query(self, text: str) -> tuple[float, ...]:
        """검색 문장을 dense 질의 벡터로 변환한다."""
        ...


class KeywordSearcher(Protocol):
    def search_keywords(self, query: KeywordQuery) -> list[SearchHit]:
        """기간을 먼저 제한한 뒤 BM25 순위 결과를 반환한다."""
        ...


class VectorStore(Protocol):
    def ensure_collection(self, vector_size: int) -> None:
        """dense·BM25 sparse 구성을 가진 검색 컬렉션을 멱등하게 준비한다."""
        ...

    def upsert_points(self, points: Sequence[VectorPoint]) -> int:
        """기사 ID 기준으로 포인트를 추가하거나 덮어쓰고 처리 건수를 반환한다."""
        ...

    def search_vector(
        self,
        vector: Sequence[float],
        options: SearchOptions,
    ) -> list[SearchHit]:
        """기간을 먼저 제한한 뒤 dense 벡터 순위 결과를 반환한다."""
        ...


class Repository(Protocol):
    def upsert_articles(self, articles: Sequence[Article]) -> int:
        """기사를 ID 기준으로 추가하거나 덮어쓰고 처리 건수를 반환한다."""
        ...

    def get_article(self, article_id: int) -> Article | None:
        """기사 한 건을 조회한다."""
        ...

    def get_articles(self, article_ids: Sequence[int]) -> list[Article]:
        """존재하는 기사만 입력 ID 순서로 반환한다."""
        ...

    def save_issue(self, issue: IssueCreate) -> int:
        """이슈·이벤트·기사 연결을 원자적으로 저장하고 ID를 반환한다."""
        ...

    def get_issue(self, issue_id: int) -> IssueDetail | None:
        """이슈 상세와 이벤트별 대표 기사를 조회한다."""
        ...

    def find_issue_by_topic(self, topic: str) -> IssueDetail | None:
        """재사용할 기존 이슈를 토픽으로 찾는다."""
        ...

    def find_issues_by_article(self, article_id: int) -> list[IssueCitation]:
        """특정 기사를 인용한 이슈·이벤트를 역방향으로 조회한다."""
        ...
