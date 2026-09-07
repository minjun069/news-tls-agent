"""원본 JSONL을 선택한 공급자로 임베딩하고 Qdrant 컬렉션에 적재한다."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv
from google.genai import errors as genai_errors

from core.config import load_embedding_config, load_gemini_config, load_qdrant_config
from core.models import Article, VectorPoint
from core.ports import EmbeddingProvider
from infra.embedding import create_embedding_provider
from infra.qdrant import QdrantVectorStore
from scripts.raw_ingestion import RawIngestionStats, RawValidationReport, iter_valid_articles

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_BATCH_SIZE = 32
_DEFAULT_MAX_ATTEMPTS = 7
_DEFAULT_INITIAL_BACKOFF_SECONDS = 1.0
_DEFAULT_MAX_BACKOFF_SECONDS = 60.0

logger = logging.getLogger(__name__)


class DailyEmbeddingQuotaExhaustedError(RuntimeError):
    """Gemini의 일일 임베딩 한도가 소진돼 다음 배치를 처리할 수 없다."""


class VectorBuildStore(Protocol):
    """벡터 적재 스크립트가 Qdrant 어댑터에 요구하는 최소 기능."""

    def ensure_collection(self, vector_size: int) -> None:
        """검색 컬렉션을 멱등하게 준비한다."""
        ...

    def dense_point_ids(self, article_ids: Sequence[int]) -> set[int]:
        """이미 dense 벡터가 저장된 기사 ID를 반환한다."""
        ...

    def upsert_points(self, points: Sequence[VectorPoint]) -> int:
        """기사 포인트를 멱등 upsert한다."""
        ...

    def all_point_ids(self, batch_size: int = 1_000) -> set[int]:
        """종료 검증을 위해 전체 포인트 ID를 반환한다."""
        ...


@dataclass(frozen=True)
class RetryPolicy:
    """외부 API와 Qdrant 호출의 유한 지수 백오프 설정."""

    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    initial_delay_seconds: float = _DEFAULT_INITIAL_BACKOFF_SECONDS
    max_delay_seconds: float = _DEFAULT_MAX_BACKOFF_SECONDS

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts는 1 이상이어야 합니다")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds는 0 이상이어야 합니다")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("max_delay_seconds는 initial_delay_seconds 이상이어야 합니다")


@dataclass(frozen=True)
class VectorBuildReport:
    """전체 원본 순회, 임베딩, Qdrant 정합성 검증 결과."""

    validation: RawValidationReport
    unique_article_count: int
    embedded_article_count: int
    skipped_dense_count: int
    sparse_only_count: int
    upserted_point_count: int
    collection_point_count: int
    missing_point_ids: tuple[int, ...]
    unexpected_point_ids: tuple[int, ...]

    @property
    def complete(self) -> bool:
        return (
            self.sparse_only_count == 0
            and not self.missing_point_ids
            and not self.unexpected_point_ids
        )

    def as_dict(self) -> dict[str, object]:
        return {
            **self.validation.as_dict(),
            "unique_article_count": self.unique_article_count,
            "embedded_article_count": self.embedded_article_count,
            "skipped_dense_count": self.skipped_dense_count,
            "sparse_only_count": self.sparse_only_count,
            "upserted_point_count": self.upserted_point_count,
            "collection_point_count": self.collection_point_count,
            "missing_point_count": len(self.missing_point_ids),
            "unexpected_point_count": len(self.unexpected_point_ids),
            "missing_point_ids_sample": list(self.missing_point_ids[:10]),
            "unexpected_point_ids_sample": list(self.unexpected_point_ids[:10]),
            "status": "complete" if self.complete else "partial",
        }


def build_search_text(article: Article) -> str:
    """ADR-0005 순서로 제목·요약·본문을 하나의 검색 입력으로 결합한다."""
    return " ".join(
        part.strip()
        for part in (article.title, article.summary, article.content)
        if part is not None and part.strip()
    )


def _batches(items: Iterable[Article], size: int) -> Iterable[list[Article]]:
    batch: dict[int, Article] = {}
    for item in items:
        batch[item.article_id] = item
        if len(batch) >= size:
            yield list(batch.values())
            batch = {}
    if batch:
        yield list(batch.values())


def _retry[ResultT](
    operation: Callable[[], ResultT],
    policy: RetryPolicy,
    sleep: Callable[[float], None],
    operation_name: str,
) -> ResultT:
    delay = policy.initial_delay_seconds
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if _is_daily_embedding_quota_exhausted(exc):
                raise DailyEmbeddingQuotaExhaustedError(
                    "Gemini 일일 임베딩 한도가 소진됐습니다. "
                    "사용 등급을 변경하거나 일일 한도 초기화 후 같은 명령을 재실행하세요."
                ) from exc
            if attempt == policy.max_attempts:
                raise
            logger.warning(
                "%s 실패, 재시도 예정: attempt=%d/%d delay=%.1fs error=%s",
                operation_name,
                attempt,
                policy.max_attempts,
                delay,
                exc,
            )
            sleep(delay)
            delay = min(delay * 2 if delay > 0 else 0, policy.max_delay_seconds)
    raise RuntimeError("재시도 루프가 비정상 종료됐습니다")


def _is_daily_embedding_quota_exhausted(exc: Exception) -> bool:
    if not isinstance(exc, genai_errors.APIError) or exc.code != 429:
        return False
    details = exc.details
    if not isinstance(details, Mapping):
        return False
    error = details.get("error", details)
    if not isinstance(error, Mapping):
        return False
    quota_details = error.get("details", [])
    if not isinstance(quota_details, list):
        return False
    for detail in quota_details:
        if not isinstance(detail, Mapping):
            continue
        violations = detail.get("violations", [])
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if not isinstance(violation, Mapping):
                continue
            quota_id = violation.get("quotaId", "")
            if isinstance(quota_id, str) and "EmbedContentRequestsPerDay" in quota_id:
                return True
    return False


def _point(article: Article, vector: tuple[float, ...] | None) -> VectorPoint:
    return VectorPoint(
        article_id=article.article_id,
        vector=vector,
        search_text=build_search_text(article),
        service_date=article.service_date,
        title=article.title,
        category_middle=article.category_middle,
    )


def build_vector_index(
    paths: Sequence[Path],
    *,
    batch_size: int,
    vector_size: int,
    embedding_provider: EmbeddingProvider | None,
    store: VectorBuildStore,
    retry_policy: RetryPolicy,
    resume: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> VectorBuildReport:
    """원본을 스트리밍해 dense·BM25 포인트를 적재하고 전체 ID를 대조한다."""
    if batch_size < 1:
        raise ValueError("batch_size는 1 이상이어야 합니다")
    if vector_size < 1:
        raise ValueError("vector_size는 1 이상이어야 합니다")
    if embedding_provider is None and not resume:
        raise ValueError("sparse-only 적재에는 force를 함께 사용할 수 없습니다")

    _retry(
        lambda: store.ensure_collection(vector_size),
        retry_policy,
        sleep,
        "Qdrant 컬렉션 준비",
    )
    stats = RawIngestionStats()
    source_article_ids: set[int] = set()
    embedded_count = 0
    skipped_dense_count = 0
    sparse_only_count = 0
    upserted_count = 0

    for batch_number, batch in enumerate(
        _batches(iter_valid_articles(paths, stats), batch_size),
        start=1,
    ):
        source_article_ids.update(article.article_id for article in batch)
        batch_ids = [article.article_id for article in batch]
        existing_dense_ids = (
            _retry(
                lambda batch_ids=batch_ids: store.dense_point_ids(batch_ids),
                retry_policy,
                sleep,
                "Qdrant 재개 상태 조회",
            )
            if resume
            else set()
        )
        pending = [article for article in batch if article.article_id not in existing_dense_ids]
        skipped_dense_count += len(batch) - len(pending)
        if not pending:
            continue

        if embedding_provider is None:
            points = [_point(article, None) for article in pending]
            sparse_only_count += len(points)
        else:
            pending_texts = [build_search_text(article) for article in pending]
            try:
                vectors = _retry(
                    lambda pending_texts=pending_texts: embedding_provider.embed_documents(
                        pending_texts
                    ),
                    retry_policy,
                    sleep,
                    "문서 임베딩",
                )
            except DailyEmbeddingQuotaExhaustedError:
                raise
            except Exception:
                logger.exception(
                    "dense 임베딩 최종 실패, BM25만 적재: batch=%d count=%d",
                    batch_number,
                    len(pending),
                )
                points = [_point(article, None) for article in pending]
                sparse_only_count += len(points)
            else:
                points = [
                    _point(article, vector)
                    for article, vector in zip(pending, vectors, strict=True)
                ]
                embedded_count += len(points)

        upserted_count += _retry(
            lambda points=points: store.upsert_points(points),
            retry_policy,
            sleep,
            "Qdrant 포인트 upsert",
        )
        if batch_number == 1 or batch_number % 100 == 0:
            logger.info(
                "벡터 적재 진행: batch=%d parsed=%d embedded=%d sparse_only=%d skipped=%d",
                batch_number,
                stats.valid_article_count,
                embedded_count,
                sparse_only_count,
                skipped_dense_count,
            )

    collection_ids = _retry(
        store.all_point_ids,
        retry_policy,
        sleep,
        "Qdrant 전체 ID 검증",
    )
    return VectorBuildReport(
        validation=stats.report(),
        unique_article_count=len(source_article_ids),
        embedded_article_count=embedded_count,
        skipped_dense_count=skipped_dense_count,
        sparse_only_count=sparse_only_count,
        upserted_point_count=upserted_count,
        collection_point_count=len(collection_ids),
        missing_point_ids=tuple(sorted(source_article_ids - collection_ids)),
        unexpected_point_ids=tuple(sorted(collection_ids - source_article_ids)),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="원본 JSONL 파일")
    parser.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-attempts", type=int, default=_DEFAULT_MAX_ATTEMPTS)
    parser.add_argument(
        "--initial-backoff-seconds",
        type=float,
        default=_DEFAULT_INITIAL_BACKOFF_SECONDS,
    )
    parser.add_argument(
        "--max-backoff-seconds",
        type=float,
        default=_DEFAULT_MAX_BACKOFF_SECONDS,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 dense 포인트도 다시 임베딩한다. 기본은 완료 포인트를 건너뛴다.",
    )
    parser.add_argument(
        "--sparse-only",
        action="store_true",
        help="외부 임베딩 호출 없이 BM25 포인트만 적재한다.",
    )
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size는 1 이상이어야 합니다")
    if args.force and args.sparse_only:
        parser.error("--force와 --sparse-only는 함께 사용할 수 없습니다")
    return args


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _parse_args()
    load_dotenv(_REPO_ROOT / ".env")
    qdrant_config = load_qdrant_config(os.environ)
    embedding_config = load_embedding_config(os.environ)
    vector_size = embedding_config.dimensions
    embedding_provider: EmbeddingProvider | None = None
    if not args.sparse_only:
        gemini_config = (
            load_gemini_config(os.environ) if embedding_config.provider == "gemini" else None
        )
        embedding_provider = create_embedding_provider(embedding_config, gemini_config)
    store = QdrantVectorStore(qdrant_config)
    try:
        try:
            report = build_vector_index(
                args.inputs,
                batch_size=args.batch_size,
                vector_size=vector_size,
                embedding_provider=embedding_provider,
                store=store,
                retry_policy=RetryPolicy(
                    max_attempts=args.max_attempts,
                    initial_delay_seconds=args.initial_backoff_seconds,
                    max_delay_seconds=args.max_backoff_seconds,
                ),
                resume=not args.force,
            )
        except DailyEmbeddingQuotaExhaustedError as exc:
            logger.log(logging.ERROR, "%s", exc)
            raise SystemExit(3) from None
    finally:
        store.close()
    print(
        json.dumps(
            {"inputs": [str(path) for path in args.inputs], **report.as_dict()},
            ensure_ascii=False,
        )
    )
    if not report.complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
