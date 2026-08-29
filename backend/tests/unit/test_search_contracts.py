from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from core.models import (
    KeywordOperator,
    KeywordQuery,
    SearchMethod,
    SearchOptions,
    SearchResult,
    SemanticQuery,
    VectorPoint,
)


def test_search_method_values_match_public_contract() -> None:
    assert [method.value for method in SearchMethod] == ["keyword", "semantic", "hybrid"]


def test_search_options_validate_limit_and_date_order() -> None:
    with pytest.raises(ValidationError, match="top_k"):
        SearchOptions(top_k=0)
    with pytest.raises(ValidationError, match="date_from"):
        SearchOptions(date_from=date(2026, 2, 2), date_to=date(2026, 2, 1))


def test_keyword_query_normalizes_terms_and_preserves_operator() -> None:
    query = KeywordQuery(
        terms=(" 윤석열 ", "탄핵", "윤석열"),
        operator=KeywordOperator.AND,
        date_from=date(2025, 1, 1),
        date_to=date(2025, 4, 4),
    )

    assert query.terms == ("윤석열", "탄핵")
    assert query.operator is KeywordOperator.AND


def test_keyword_query_rejects_blank_term() -> None:
    with pytest.raises(ValidationError, match="빈 문자열"):
        KeywordQuery(terms=("탄핵", "  "))


def test_semantic_query_strips_text_and_rejects_blank() -> None:
    assert SemanticQuery(text=" 계엄 해제 절차 ").text == "계엄 해제 절차"
    with pytest.raises(ValidationError, match="빈 문자열"):
        SemanticQuery(text="  ")


def test_vector_point_requires_dense_vector_and_bm25_text() -> None:
    with pytest.raises(ValidationError, match="vector"):
        VectorPoint(
            article_id=1,
            vector=(),
            search_text="기사 본문",
            service_date=date(2025, 1, 1),
            title="기사",
        )
    with pytest.raises(ValidationError, match="BM25 입력 텍스트"):
        VectorPoint(
            article_id=1,
            vector=(0.1, 0.2),
            search_text="  ",
            service_date=date(2025, 1, 1),
            title="기사",
        )


def test_vector_point_allows_sparse_only_point_when_dense_embedding_failed() -> None:
    point = VectorPoint(
        article_id=1,
        search_text="기사 본문",
        service_date=date(2025, 1, 1),
        title="기사",
    )

    assert point.vector is None


def test_search_result_is_immutable() -> None:
    result = SearchResult(method=SearchMethod.HYBRID, hits=())

    with pytest.raises(ValidationError, match="frozen"):
        result.method = SearchMethod.KEYWORD
