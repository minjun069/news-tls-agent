from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.search import ArticleSearchService
from core.models import (
    ArticleSearchRequest,
    KeywordOperator,
    SearchHit,
    SearchMethod,
    SearchOptions,
)


class FakeKeywordSearcher:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.queries = []

    def search_keywords(self, query):
        self.queries.append(query)
        return self.hits


class FakeVectorStore:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls = []

    def search_vector(self, vector, options):
        self.calls.append((tuple(vector), options))
        return self.hits


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.queries = []

    def embed_query(self, text: str) -> tuple[float, ...]:
        self.queries.append(text)
        return (0.1, 0.2)


def build_service(
    keyword_hits: list[SearchHit], vector_hits: list[SearchHit]
) -> tuple[ArticleSearchService, FakeKeywordSearcher, FakeVectorStore, FakeEmbeddingProvider]:
    keyword = FakeKeywordSearcher(keyword_hits)
    vector = FakeVectorStore(vector_hits)
    embedding = FakeEmbeddingProvider()
    return ArticleSearchService(keyword, vector, embedding), keyword, vector, embedding


def test_keyword_search_preserves_query_and_period_without_embedding() -> None:
    service, keyword, vector, embedding = build_service([SearchHit(article_id=1, score=2.0)], [])
    options = SearchOptions(
        top_k=7,
        date_from=date(2025, 1, 1),
        date_to=date(2025, 2, 1),
    )

    result = service.search(" 윤석열 탄핵 ", SearchMethod.KEYWORD, options)

    assert result.method is SearchMethod.KEYWORD
    assert [hit.article_id for hit in result.hits] == [1]
    assert keyword.queries[0].terms == ("윤석열 탄핵",)
    assert keyword.queries[0].top_k == 7
    assert keyword.queries[0].date_from == date(2025, 1, 1)
    assert vector.calls == []
    assert embedding.queries == []


def test_semantic_search_embeds_query_and_passes_options() -> None:
    service, keyword, vector, embedding = build_service([], [SearchHit(article_id=2, score=0.8)])
    options = SearchOptions(top_k=3)

    result = service.search(" 계엄 해제 절차 ", SearchMethod.SEMANTIC, options)

    assert result.method is SearchMethod.SEMANTIC
    assert [hit.article_id for hit in result.hits] == [2]
    assert embedding.queries == ["계엄 해제 절차"]
    assert vector.calls[0][0] == (0.1, 0.2)
    assert vector.calls[0][1].top_k == 3
    assert keyword.queries == []


def test_hybrid_search_fuses_keyword_and_semantic_rankings() -> None:
    service, keyword, vector, embedding = build_service(
        [SearchHit(article_id=1, score=10), SearchHit(article_id=2, score=5)],
        [SearchHit(article_id=2, score=0.9), SearchHit(article_id=3, score=0.8)],
    )

    result = service.search("국회 표결", SearchMethod.HYBRID, SearchOptions(top_k=3))

    assert result.method is SearchMethod.HYBRID
    assert [hit.article_id for hit in result.hits] == [2, 1, 3]
    assert len(keyword.queries) == 1
    assert len(vector.calls) == 1
    assert embedding.queries == ["국회 표결"]


def test_search_rejects_blank_query_before_calling_adapters() -> None:
    service, keyword, vector, embedding = build_service([], [])

    with pytest.raises(ValidationError, match="빈 문자열"):
        service.search("  ", SearchMethod.HYBRID, SearchOptions())

    assert keyword.queries == []
    assert vector.calls == []
    assert embedding.queries == []


def test_planned_hybrid_search_preserves_keyword_terms_and_semantic_text() -> None:
    service, keyword, vector, embedding = build_service(
        [SearchHit(article_id=1, score=2)],
        [SearchHit(article_id=2, score=0.8)],
    )
    request = ArticleSearchRequest(
        method=SearchMethod.HYBRID,
        options=SearchOptions(top_k=5, date_from=date(2025, 1, 1)),
        keyword_terms=("윤석열", "탄핵"),
        keyword_operator=KeywordOperator.AND,
        semantic_text="대통령 탄핵 심판 진행",
    )

    result = service.search_request(request)

    assert result.method is SearchMethod.HYBRID
    assert keyword.queries[0].terms == ("윤석열", "탄핵")
    assert keyword.queries[0].operator is KeywordOperator.AND
    assert embedding.queries == ["대통령 탄핵 심판 진행"]
    assert vector.calls[0][1].date_from == date(2025, 1, 1)
