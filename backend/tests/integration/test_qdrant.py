"""실제 Qdrant 서버에서 dense·BM25·기간 필터 계약을 검증한다."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ApiException, ResponseHandlingException

from core.config import QdrantConfig
from core.models import KeywordOperator, KeywordQuery, SearchOptions, VectorPoint
from infra.qdrant import BM25_VECTOR_NAME, DENSE_VECTOR_NAME, QdrantVectorStore

pytestmark = pytest.mark.integration


class QdrantContext:
    def __init__(
        self,
        store: QdrantVectorStore,
        client: QdrantClient,
        collection: str,
    ) -> None:
        self.store = store
        self.client = client
        self.collection = collection


@pytest.fixture(scope="module")
def context() -> Iterator[QdrantContext]:
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    collection = f"integration_{uuid4().hex}"
    client = QdrantClient(url=url, timeout=10)
    try:
        client.get_collections()
    except (ApiException, ResponseHandlingException) as exc:
        pytest.fail(f"Qdrant 서버에 연결할 수 없습니다: {url}: {exc}")

    store = QdrantVectorStore(QdrantConfig(url=url, collection=collection), client=client)
    store.ensure_collection(vector_size=3)
    store.upsert_points(
        (
            _point(
                91001,
                vector=(1.0, 0.0, 0.0),
                search_text="영남 산불 주민 대피",
                service_date=date(2025, 3, 22),
                title="영남 산불 대피령",
            ),
            _point(
                91002,
                vector=(0.9, 0.1, 0.0),
                search_text="영남 산불 피해 복구",
                service_date=date(2025, 4, 2),
                title="영남 산불 복구 착수",
            ),
            _point(
                91003,
                vector=(0.0, 1.0, 0.0),
                search_text="통신사 유심 정보 유출",
                service_date=date(2025, 5, 1),
                title="유심 정보 유출 조사",
            ),
        )
    )
    try:
        yield QdrantContext(store, client, collection)
    finally:
        client.delete_collection(collection)
        client.close()


def _point(
    article_id: int,
    *,
    vector: tuple[float, float, float],
    search_text: str,
    service_date: date,
    title: str,
) -> VectorPoint:
    return VectorPoint(
        article_id=article_id,
        vector=vector,
        search_text=search_text,
        service_date=service_date,
        title=title,
        category_middle="사회",
    )


def test_real_collection_upsert_and_payload_contract(context: QdrantContext) -> None:
    assert context.client.count(context.collection, exact=True).count == 3
    assert context.store.all_point_ids(batch_size=2) == {91001, 91002, 91003}
    assert context.store.dense_point_ids([91001, 91002, 99999]) == {91001, 91002}

    records = context.client.retrieve(
        context.collection,
        ids=[91001, 91002, 91003],
        with_payload=True,
        with_vectors=False,
    )
    assert {record.id for record in records} == {91001, 91002, 91003}
    assert set(records[0].payload or {}) == {
        "article_id",
        "service_date",
        "title",
        "category_middle",
    }

    params = context.client.get_collection(context.collection).config.params
    assert isinstance(params.vectors, dict)
    assert params.vectors[DENSE_VECTOR_NAME].distance is models.Distance.COSINE
    assert params.sparse_vectors is not None
    assert params.sparse_vectors[BM25_VECTOR_NAME].modifier is models.Modifier.IDF


def test_real_dense_and_bm25_search_apply_date_filter(context: QdrantContext) -> None:
    dense = context.store.search_vector(
        (1.0, 0.0, 0.0),
        SearchOptions(
            top_k=3,
            date_from=date(2025, 3, 1),
            date_to=date(2025, 4, 30),
        ),
    )
    assert [hit.article_id for hit in dense] == [91001, 91002]

    keyword_or = context.store.search_keywords(
        KeywordQuery(
            terms=("영남", "복구"),
            operator=KeywordOperator.OR,
            top_k=3,
            date_from=date(2025, 3, 1),
            date_to=date(2025, 4, 30),
        )
    )
    assert {hit.article_id for hit in keyword_or} == {91001, 91002}

    keyword_and = context.store.search_keywords(
        KeywordQuery(
            terms=("영남", "복구"),
            operator=KeywordOperator.AND,
            top_k=3,
            date_from=date(2025, 3, 1),
            date_to=date(2025, 4, 30),
        )
    )
    assert [hit.article_id for hit in keyword_and] == [91002]

    outside_period = context.store.search_keywords(
        KeywordQuery(
            terms=("영남", "복구"),
            operator=KeywordOperator.AND,
            top_k=3,
            date_from=date(2025, 3, 1),
            date_to=date(2025, 3, 31),
        )
    )
    assert outside_period == []
