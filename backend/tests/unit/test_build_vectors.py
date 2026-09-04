from __future__ import annotations

import importlib
import json
from datetime import date
from pathlib import Path

import pytest
from google.genai.errors import ClientError

from core.models import VectorPoint

builder = importlib.import_module("scripts.03_build_vectors")


def raw_article(article_id: int, title: str) -> dict[str, object]:
    return {
        "article_id": article_id,
        "article_title": title,
        "article_service_daytime": "2025-01-02 09:00:00",
        "article_summary": f"{title} 요약",
        "text": f"{title} 본문",
        "category_middle_nm": "사회",
    }


def write_raw(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class FakeEmbeddingProvider:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[list[str]] = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("quota exceeded")
        return [(float(index), 0.5) for index, _text in enumerate(texts, start=1)]

    def embed_query(self, text):
        raise NotImplementedError


class DailyQuotaEmbeddingProvider:
    def __init__(self) -> None:
        self.call_count = 0

    def embed_documents(self, _texts):
        self.call_count += 1
        raise ClientError(
            429,
            {
                "error": {
                    "details": [
                        {
                            "violations": [
                                {
                                    "quotaId": (
                                        "EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier"
                                    )
                                }
                            ]
                        }
                    ]
                }
            },
        )

    def embed_query(self, _text):
        raise NotImplementedError


class FakeStore:
    def __init__(self, dense_ids=None, extra_ids=None) -> None:
        self.dense_ids = set(dense_ids or set())
        self.point_ids = set(self.dense_ids) | set(extra_ids or set())
        self.vector_size = None
        self.upserted: list[list[VectorPoint]] = []

    def ensure_collection(self, vector_size):
        self.vector_size = vector_size

    def dense_point_ids(self, article_ids):
        return self.dense_ids.intersection(article_ids)

    def upsert_points(self, points):
        stored = list(points)
        self.upserted.append(stored)
        self.point_ids.update(point.article_id for point in stored)
        self.dense_ids.update(point.article_id for point in stored if point.vector is not None)
        return len(stored)

    def all_point_ids(self, batch_size=1_000):
        return set(self.point_ids)


def policy(max_attempts: int = 1) -> builder.RetryPolicy:
    return builder.RetryPolicy(
        max_attempts=max_attempts,
        initial_delay_seconds=0,
        max_delay_seconds=0,
    )


def test_build_vector_index_streams_raw_and_resumes_existing_dense(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    write_raw(source, [raw_article(1, "첫 기사"), raw_article(2, "둘째 기사")])
    provider = FakeEmbeddingProvider()
    store = FakeStore(dense_ids={2})

    report = builder.build_vector_index(
        [source],
        batch_size=2,
        vector_size=3072,
        embedding_provider=provider,
        store=store,
        retry_policy=policy(),
        sleep=lambda _seconds: None,
    )

    assert report.complete is True
    assert report.unique_article_count == 2
    assert report.embedded_article_count == 1
    assert report.skipped_dense_count == 1
    assert report.collection_point_count == 2
    assert store.vector_size == 3072
    assert [point.article_id for point in store.upserted[0]] == [1]
    assert provider.calls == [["첫 기사 첫 기사 요약 첫 기사 본문"]]


def test_embedding_retries_before_upsert(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    write_raw(source, [raw_article(1, "기사")])
    provider = FakeEmbeddingProvider(failures=1)
    store = FakeStore()
    sleeps: list[float] = []

    report = builder.build_vector_index(
        [source],
        batch_size=1,
        vector_size=2,
        embedding_provider=provider,
        store=store,
        retry_policy=builder.RetryPolicy(2, 0.5, 1),
        sleep=sleeps.append,
    )

    assert report.complete is True
    assert len(provider.calls) == 2
    assert sleeps == [0.5]
    assert store.upserted[0][0].vector == (1.0, 0.5)


def test_final_embedding_failure_keeps_sparse_point_and_reports_partial(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    write_raw(source, [raw_article(1, "기사")])
    store = FakeStore()

    report = builder.build_vector_index(
        [source],
        batch_size=1,
        vector_size=2,
        embedding_provider=FakeEmbeddingProvider(failures=1),
        store=store,
        retry_policy=policy(),
        sleep=lambda _seconds: None,
    )

    assert report.complete is False
    assert report.sparse_only_count == 1
    assert store.upserted[0][0].vector is None
    assert report.as_dict()["status"] == "partial"


def test_sparse_only_build_does_not_require_embedding_provider(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    write_raw(source, [raw_article(1, "기사")])
    store = FakeStore()

    report = builder.build_vector_index(
        [source],
        batch_size=1,
        vector_size=3072,
        embedding_provider=None,
        store=store,
        retry_policy=policy(),
        sleep=lambda _seconds: None,
    )

    assert report.sparse_only_count == 1
    assert store.upserted[0][0].vector is None


def test_collection_id_mismatch_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    write_raw(source, [raw_article(1, "기사")])
    store = FakeStore(extra_ids={99})

    report = builder.build_vector_index(
        [source],
        batch_size=1,
        vector_size=2,
        embedding_provider=FakeEmbeddingProvider(),
        store=store,
        retry_policy=policy(),
        sleep=lambda _seconds: None,
    )

    assert report.complete is False
    assert report.unexpected_point_ids == (99,)


def test_build_search_text_uses_title_summary_content_order() -> None:
    article = builder.Article(
        article_id=1,
        title="제목",
        summary="요약",
        content="본문",
        service_date=date(2025, 1, 2),
    )

    assert builder.build_search_text(article) == "제목 요약 본문"


def test_retry_policy_and_batch_size_reject_invalid_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        policy(0)
    with pytest.raises(ValueError, match="batch_size"):
        builder.build_vector_index(
            [tmp_path / "unused.jsonl"],
            batch_size=0,
            vector_size=2,
            embedding_provider=FakeEmbeddingProvider(),
            store=FakeStore(),
            retry_policy=policy(),
        )


def test_sparse_only_force_is_rejected_to_preserve_existing_dense(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"sparse-only.*force"):
        builder.build_vector_index(
            [tmp_path / "unused.jsonl"],
            batch_size=1,
            vector_size=2,
            embedding_provider=None,
            store=FakeStore(),
            retry_policy=policy(),
            resume=False,
        )


def test_daily_embedding_quota_stops_without_sparse_fallback(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    write_raw(source, [raw_article(1, "기사")])
    provider = DailyQuotaEmbeddingProvider()
    store = FakeStore()

    with pytest.raises(builder.DailyEmbeddingQuotaExhaustedError):
        builder.build_vector_index(
            [source],
            batch_size=1,
            vector_size=2,
            embedding_provider=provider,
            store=store,
            retry_policy=builder.RetryPolicy(7, 0, 0),
            sleep=lambda _seconds: None,
        )

    assert store.upserted == []
    assert provider.call_count == 1
