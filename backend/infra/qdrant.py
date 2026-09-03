"""Qdrant dense 의미 검색·BM25 키워드 검색 어댑터."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from qdrant_client import QdrantClient
from qdrant_client.http import models

from core.config import QdrantConfig
from core.models import KeywordOperator, KeywordQuery, SearchHit, SearchOptions, VectorPoint

DENSE_VECTOR_NAME = "dense"
BM25_VECTOR_NAME = "bm25"
BM25_MODEL = "qdrant/bm25"


class CollectionConfigurationError(Exception):
    """기존 컬렉션의 검색 구성이 현재 계약과 다르다."""


class QdrantVectorStore:
    """한 컬렉션에서 dense 벡터와 BM25 sparse 표현을 관리한다."""

    def __init__(self, config: QdrantConfig, client: QdrantClient | None = None) -> None:
        self._collection = config.collection
        self._client = client if client is not None else QdrantClient(url=config.url)

    def ensure_collection(self, vector_size: int) -> None:
        if vector_size < 1:
            raise ValueError("dense 벡터 차원은 1 이상이어야 합니다")

        if self._client.collection_exists(self._collection):
            self._validate_collection(vector_size)
            return

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                BM25_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )

    def upsert_points(self, points: Sequence[VectorPoint]) -> int:
        if not points:
            return 0
        self._client.upsert(
            collection_name=self._collection,
            points=[_to_point_struct(point) for point in points],
            wait=True,
        )
        return len(points)

    def search_vector(
        self,
        vector: Sequence[float],
        options: SearchOptions,
    ) -> list[SearchHit]:
        if not vector:
            raise ValueError("검색 벡터는 비어 있을 수 없습니다")
        response = self._client.query_points(
            collection_name=self._collection,
            query=list(vector),
            using=DENSE_VECTOR_NAME,
            query_filter=_date_filter(options),
            limit=options.top_k,
            with_payload=False,
            with_vectors=False,
        )
        return _to_search_hits(response.points)

    def search_keywords(self, query: KeywordQuery) -> list[SearchHit]:
        query_filter = _date_filter(query)
        candidate_count = self._client.count(
            collection_name=self._collection,
            count_filter=query_filter,
            exact=True,
        ).count
        if candidate_count == 0:
            return []

        scores: dict[int, float] = {}
        matched_terms: dict[int, int] = {}
        for term in query.terms:
            response = self._client.query_points(
                collection_name=self._collection,
                query=_bm25_document(term),
                using=BM25_VECTOR_NAME,
                query_filter=query_filter,
                limit=candidate_count,
                with_payload=False,
                with_vectors=False,
            )
            for hit in _to_search_hits(response.points):
                scores[hit.article_id] = scores.get(hit.article_id, 0.0) + hit.score
                matched_terms[hit.article_id] = matched_terms.get(hit.article_id, 0) + 1

        required_matches = len(query.terms) if query.operator is KeywordOperator.AND else 1
        combined = (
            SearchHit(article_id=article_id, score=score)
            for article_id, score in scores.items()
            if matched_terms[article_id] >= required_matches
        )
        return sorted(combined, key=lambda hit: (-hit.score, hit.article_id))[: query.top_k]

    def _validate_collection(self, vector_size: int) -> None:
        params = self._client.get_collection(self._collection).config.params
        dense_vectors = params.vectors
        sparse_vectors = params.sparse_vectors

        if not isinstance(dense_vectors, Mapping) or DENSE_VECTOR_NAME not in dense_vectors:
            raise CollectionConfigurationError("기존 컬렉션에 dense named vector가 없습니다")
        dense = dense_vectors[DENSE_VECTOR_NAME]
        if dense.size != vector_size or dense.distance is not models.Distance.COSINE:
            raise CollectionConfigurationError(
                "기존 dense vector의 차원 또는 거리 함수가 현재 계약과 다릅니다"
            )
        if sparse_vectors is None or BM25_VECTOR_NAME not in sparse_vectors:
            raise CollectionConfigurationError("기존 컬렉션에 bm25 sparse vector가 없습니다")
        if sparse_vectors[BM25_VECTOR_NAME].modifier is not models.Modifier.IDF:
            raise CollectionConfigurationError("기존 bm25 sparse vector에 IDF modifier가 없습니다")


def _bm25_document(text: str) -> models.Document:
    return models.Document(
        text=text,
        model=BM25_MODEL,
        options=models.Bm25Config(
            tokenizer=models.TokenizerType.MULTILINGUAL,
            stemmer=models.DisabledStemmerParams(type=models.NoStemmer.NONE),
            stopwords=models.StopwordsSet(),
        ),
    )


def _to_point_struct(point: VectorPoint) -> models.PointStruct:
    vectors: dict[str, list[float] | models.Document] = {
        BM25_VECTOR_NAME: _bm25_document(point.search_text)
    }
    if point.vector is not None:
        vectors[DENSE_VECTOR_NAME] = list(point.vector)
    return models.PointStruct(
        id=point.article_id,
        vector=vectors,
        payload={
            "article_id": point.article_id,
            "service_date": point.service_date.isoformat(),
            "title": point.title,
            "category_middle": point.category_middle,
        },
    )


def _date_filter(options: SearchOptions) -> models.Filter | None:
    if options.date_from is None and options.date_to is None:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(
                key="service_date",
                range=models.DatetimeRange(gte=options.date_from, lte=options.date_to),
            )
        ]
    )


def _to_search_hits(points: Sequence[models.ScoredPoint]) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for point in points:
        if not isinstance(point.id, int) or isinstance(point.id, bool):
            raise TypeError(f"Qdrant 포인트 ID가 기사 정수 ID가 아닙니다: {point.id!r}")
        hits.append(SearchHit(article_id=point.id, score=point.score))
    return hits
