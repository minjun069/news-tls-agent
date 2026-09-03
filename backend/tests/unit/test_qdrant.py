from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from qdrant_client.http import models

from core.config import QdrantConfig
from core.models import KeywordOperator, KeywordQuery, SearchOptions, VectorPoint
from infra.qdrant import (
    BM25_VECTOR_NAME,
    DENSE_VECTOR_NAME,
    CollectionConfigurationError,
    QdrantVectorStore,
)


class FakeQdrantClient:
    def __init__(self) -> None:
        self.exists = False
        self.collection_info = None
        self.created = []
        self.upserts = []
        self.counts = []
        self.queries = []
        self.query_responses = []
        self.count_value = 0
        self.error: Exception | None = None

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs):
        self.created.append(kwargs)

    def get_collection(self, collection_name: str):
        return self.collection_info

    def upsert(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.upserts.append(kwargs)

    def count(self, **kwargs):
        self.counts.append(kwargs)
        return SimpleNamespace(count=self.count_value)

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(points=self.query_responses.pop(0))


def store(client: FakeQdrantClient) -> QdrantVectorStore:
    return QdrantVectorStore(
        QdrantConfig(url="http://qdrant.test:6333", collection="articles"),
        client=client,
    )


def scored(article_id: int, score: float):
    return SimpleNamespace(id=article_id, score=score)


def point(article_id: int = 7, vector: tuple[float, ...] | None = (0.1, 0.2)):
    return VectorPoint(
        article_id=article_id,
        vector=vector,
        search_text="기사 제목 기사 요약 기사 본문",
        service_date=date(2025, 1, 2),
        title="기사 제목",
        category_middle="정치",
    )


def test_store_builds_sdk_client_with_configured_url(monkeypatch) -> None:
    captured = {}
    fake_client = FakeQdrantClient()

    def build_client(*, url: str):
        captured["url"] = url
        return fake_client

    monkeypatch.setattr("infra.qdrant.QdrantClient", build_client)

    QdrantVectorStore(QdrantConfig(url="http://qdrant.test:6333", collection="articles"))

    assert captured == {"url": "http://qdrant.test:6333"}


def test_ensure_collection_creates_dense_and_bm25_named_vectors() -> None:
    client = FakeQdrantClient()

    store(client).ensure_collection(vector_size=768)

    created = client.created[0]
    assert created["collection_name"] == "articles"
    dense = created["vectors_config"][DENSE_VECTOR_NAME]
    assert dense.size == 768
    assert dense.distance is models.Distance.COSINE
    sparse = created["sparse_vectors_config"][BM25_VECTOR_NAME]
    assert sparse.modifier is models.Modifier.IDF


def test_ensure_collection_accepts_compatible_existing_collection() -> None:
    client = FakeQdrantClient()
    client.exists = True
    client.collection_info = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors={
                    DENSE_VECTOR_NAME: models.VectorParams(
                        size=768,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors={
                    BM25_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        )
    )

    store(client).ensure_collection(vector_size=768)

    assert client.created == []


def test_ensure_collection_rejects_incompatible_existing_collection() -> None:
    client = FakeQdrantClient()
    client.exists = True
    client.collection_info = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors={
                    DENSE_VECTOR_NAME: models.VectorParams(
                        size=384,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors={
                    BM25_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        )
    )

    with pytest.raises(CollectionConfigurationError, match="차원"):
        store(client).ensure_collection(vector_size=768)


def test_upsert_uses_article_id_named_vectors_and_four_payload_fields() -> None:
    client = FakeQdrantClient()

    assert store(client).upsert_points([point()]) == 1

    call = client.upserts[0]
    assert call["collection_name"] == "articles"
    assert call["wait"] is True
    stored = call["points"][0]
    assert stored.id == 7
    assert stored.vector[DENSE_VECTOR_NAME] == [0.1, 0.2]
    bm25 = stored.vector[BM25_VECTOR_NAME]
    assert bm25.text == "기사 제목 기사 요약 기사 본문"
    assert bm25.options.tokenizer is models.TokenizerType.MULTILINGUAL
    assert bm25.options.stemmer.type is models.NoStemmer.NONE
    assert bm25.options.stopwords.model_dump(exclude_none=True) == {}
    assert stored.payload == {
        "article_id": 7,
        "service_date": "2025-01-02",
        "title": "기사 제목",
        "category_middle": "정치",
    }


def test_upsert_allows_sparse_only_and_reuses_article_id() -> None:
    client = FakeQdrantClient()
    vector_store = store(client)

    vector_store.upsert_points([point(article_id=9, vector=None)])
    vector_store.upsert_points([point(article_id=9, vector=None)])

    first = client.upserts[0]["points"][0]
    second = client.upserts[1]["points"][0]
    assert DENSE_VECTOR_NAME not in first.vector
    assert first.id == second.id == 9


def test_vector_search_applies_date_filter_before_top_k() -> None:
    client = FakeQdrantClient()
    client.query_responses = [[scored(3, 0.9), scored(8, 0.7)]]
    options = SearchOptions(
        top_k=2,
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31),
    )

    results = store(client).search_vector([0.1, 0.2], options)

    assert [(result.article_id, result.score) for result in results] == [(3, 0.9), (8, 0.7)]
    call = client.queries[0]
    assert call["using"] == DENSE_VECTOR_NAME
    assert call["limit"] == 2
    date_range = call["query_filter"].must[0].range
    assert date_range.gte == date(2025, 1, 1)
    assert date_range.lte == date(2025, 1, 31)


def test_keyword_or_sums_term_scores_then_applies_top_k() -> None:
    client = FakeQdrantClient()
    client.count_value = 4
    client.query_responses = [
        [scored(1, 0.9), scored(2, 0.5)],
        [scored(2, 0.8), scored(3, 0.7)],
    ]
    query = KeywordQuery(
        terms=("계엄", "해제"),
        operator=KeywordOperator.OR,
        top_k=2,
        date_from=date(2024, 12, 1),
    )

    results = store(client).search_keywords(query)

    assert [(result.article_id, result.score) for result in results] == [
        (2, pytest.approx(1.3)),
        (1, 0.9),
    ]
    assert client.counts[0]["exact"] is True
    assert all(call["limit"] == 4 for call in client.queries)
    assert all(call["query_filter"] is client.counts[0]["count_filter"] for call in client.queries)
    assert [call["query"].text for call in client.queries] == ["계엄", "해제"]


def test_keyword_and_keeps_only_articles_found_for_every_term() -> None:
    client = FakeQdrantClient()
    client.count_value = 3
    client.query_responses = [
        [scored(1, 0.9), scored(2, 0.5)],
        [scored(2, 0.8), scored(3, 0.7)],
    ]

    results = store(client).search_keywords(
        KeywordQuery(terms=("계엄", "해제"), operator=KeywordOperator.AND, top_k=5)
    )

    assert [(result.article_id, result.score) for result in results] == [(2, pytest.approx(1.3))]


def test_keyword_score_tie_is_broken_by_article_id() -> None:
    client = FakeQdrantClient()
    client.count_value = 2
    client.query_responses = [[scored(20, 0.5), scored(10, 0.5)]]

    results = store(client).search_keywords(KeywordQuery(terms=("계엄",), top_k=2))

    assert [result.article_id for result in results] == [10, 20]


def test_empty_date_range_and_zero_candidates_avoid_unneeded_queries() -> None:
    client = FakeQdrantClient()

    assert store(client).search_keywords(KeywordQuery(terms=("계엄",))) == []

    assert client.counts[0]["count_filter"] is None
    assert client.queries == []


def test_qdrant_sdk_error_is_not_swallowed() -> None:
    client = FakeQdrantClient()
    client.error = RuntimeError("qdrant unavailable")

    with pytest.raises(RuntimeError, match="qdrant unavailable"):
        store(client).upsert_points([point()])


def test_qdrant_non_integer_point_id_is_rejected() -> None:
    client = FakeQdrantClient()
    client.query_responses = [[SimpleNamespace(id="article-3", score=0.9)]]

    with pytest.raises(TypeError, match="정수 ID"):
        store(client).search_vector([0.1, 0.2], SearchOptions())
