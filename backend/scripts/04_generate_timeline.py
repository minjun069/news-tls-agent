"""토픽으로 S5 타임라인 파이프라인을 실행한다."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from app.pipeline import TimelinePipeline
from app.search import ArticleSearchService
from core.config import load_settings
from core.models import GenerationStatus, PipelineProgress
from infra.db import create_db_engine, create_session_factory
from infra.embedding import create_embedding_provider
from infra.gemini import GeminiStructuredGenerator
from infra.qdrant import QdrantVectorStore
from infra.repository import SqlRepository

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG_PATH = _REPOSITORY_ROOT / "logs" / "pipeline.log"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", help="생성하거나 재사용할 뉴스 토픽")
    parser.add_argument("--clarification", help="P1 되묻기에 대한 사용자 보충 답변")
    parser.add_argument(
        "--clarification-count",
        type=int,
        default=0,
        help="현재 요청 전까지 수행한 되묻기 횟수",
    )
    return parser.parse_args(argv)


def _configure_logging() -> None:
    _DEFAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(_DEFAULT_LOG_PATH, encoding="utf-8")],
        force=True,
    )


def _print_progress(progress: PipelineProgress) -> None:
    print(progress.model_dump_json())


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv(_REPOSITORY_ROOT / ".env")
    _configure_logging()
    settings = load_settings(os.environ)
    engine = create_db_engine(settings.mssql)
    repository = SqlRepository(create_session_factory(engine))
    vector_store = QdrantVectorStore(settings.qdrant)
    embedding = create_embedding_provider(settings.embedding, settings.gemini)
    searcher = ArticleSearchService(vector_store, vector_store, embedding)
    generator = GeminiStructuredGenerator(settings.gemini)
    pipeline = TimelinePipeline(
        repository,
        searcher,
        generator,
        settings.timeline,
        progress_sink=_print_progress,
    )
    result = pipeline.generate(
        args.topic,
        clarification_answer=args.clarification,
        clarification_count=args.clarification_count,
    )
    print(result.model_dump_json())
    if result.status is GenerationStatus.NEEDS_CLARIFICATION:
        return 2
    if result.status is GenerationStatus.NO_ARTICLES:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
