"""실제 뉴스 표본으로 로컬 임베딩 모델의 CPU 검색 품질과 처리량을 비교한다."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from core.models import Article
from scripts.raw_ingestion import RawIngestionStats, iter_valid_articles

_ARTICLE_COUNT = 178_887
_QWEN_QUERY_PROMPT = (
    "Instruct: Given a Korean news search query, retrieve relevant Korean news articles "
    "that answer the query\nQuery:"
)


@dataclass(frozen=True)
class QueryCase:
    query: str
    needles: tuple[str, ...]


_QUERY_CASES = (
    QueryCase("추경호 계엄 해제 방해", ("추경호", "계엄 해제")),
    QueryCase("통신사 고객 유심 정보가 유출된 사고", ("SK텔레콤", "유심")),
    QueryCase("의대 정원 확대를 둘러싼 정부와 의료계 갈등", ("의대 정원", "의료")),
    QueryCase("산불 피해 주민 지원과 복구 대책", ("산불", "복구")),
)


def _rss_mebibytes() -> float:
    status = Path("/proc/self/status").read_text(encoding="utf-8")
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    raise RuntimeError("/proc/self/status에서 VmRSS를 찾지 못했습니다")


def _search_text(article: Article) -> str:
    return " ".join(
        part.strip()
        for part in (article.title, article.summary, article.content)
        if part is not None and part.strip()
    )


def _stable_priority(article_id: int) -> int:
    digest = hashlib.sha256(str(article_id).encode()).digest()
    return int.from_bytes(digest[:8])


def _sample_articles(
    paths: Sequence[Path],
    *,
    random_count: int,
    targeted_count_per_case: int,
) -> tuple[list[Article], dict[str, set[int]]]:
    stats = RawIngestionStats()
    random_heap: list[tuple[int, int, Article]] = []
    targeted: dict[str, list[Article]] = {case.query: [] for case in _QUERY_CASES}

    for article in iter_valid_articles(paths, stats):
        priority = _stable_priority(article.article_id)
        entry = (-priority, article.article_id, article)
        if len(random_heap) < random_count:
            heapq.heappush(random_heap, entry)
        elif priority < -random_heap[0][0]:
            heapq.heapreplace(random_heap, entry)

        searchable = f"{article.title} {article.summary or ''}"
        for case in _QUERY_CASES:
            matches = targeted[case.query]
            if len(matches) < targeted_count_per_case and all(
                needle in searchable for needle in case.needles
            ):
                matches.append(article)

    by_id = {entry[2].article_id: entry[2] for entry in random_heap}
    relevant_ids: dict[str, set[int]] = {}
    for query, matches in targeted.items():
        relevant_ids[query] = {article.article_id for article in matches}
        by_id.update((article.article_id, article) for article in matches)
    return sorted(by_id.values(), key=lambda article: article.article_id), relevant_ids


def _query_prompt(model_name: str) -> str | None:
    return _QWEN_QUERY_PROMPT if "qwen3-embedding" in model_name.lower() else None


def _top_results(
    articles: Sequence[Article],
    document_vectors: np.ndarray,
    query_vector: np.ndarray,
    *,
    limit: int,
) -> list[dict[str, object]]:
    scores = document_vectors @ query_vector
    positions = np.argsort(-scores, kind="stable")[:limit]
    return [
        {
            "rank": rank,
            "article_id": articles[position].article_id,
            "title": articles[position].title,
            "service_date": articles[position].service_date.isoformat(),
            "score": float(scores[position]),
        }
        for rank, position in enumerate(positions, start=1)
    ]


def benchmark(args: argparse.Namespace) -> dict[str, object]:
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    torch.set_num_threads(args.threads)
    before_load_rss = _rss_mebibytes()
    load_started = time.perf_counter()
    model = SentenceTransformer(args.model, device="cpu")
    model.max_seq_length = args.max_seq_length
    load_seconds = time.perf_counter() - load_started
    after_load_rss = _rss_mebibytes()

    sample_started = time.perf_counter()
    articles, relevant_ids = _sample_articles(
        args.inputs,
        random_count=args.random_count,
        targeted_count_per_case=args.targeted_count_per_case,
    )
    sample_seconds = time.perf_counter() - sample_started
    texts = [_search_text(article) for article in articles]

    embedding_started = time.perf_counter()
    document_vectors = model.encode(
        texts,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    embedding_seconds = time.perf_counter() - embedding_started
    after_embedding_rss = _rss_mebibytes()

    query_results: dict[str, object] = {}
    prompt = _query_prompt(args.model)
    for case in _QUERY_CASES:
        query_vector = model.encode(
            case.query,
            prompt=prompt,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        top_results = _top_results(
            articles,
            document_vectors,
            query_vector,
            limit=args.top_k,
        )
        relevant = relevant_ids[case.query]
        query_results[case.query] = {
            "targeted_sample_count": len(relevant),
            "targeted_hits_at_k": sum(
                int(result["article_id"] in relevant) for result in top_results
            ),
            "results": top_results,
        }

    throughput = len(articles) / embedding_seconds
    vector_dimensions = int(document_vectors.shape[1])
    return {
        "model": args.model,
        "device": "cpu",
        "threads": args.threads,
        "max_seq_length": args.max_seq_length,
        "batch_size": args.batch_size,
        "normalize_embeddings": True,
        "query_prompt": prompt or "",
        "load_seconds": load_seconds,
        "model_rss_increase_mib": after_load_rss - before_load_rss,
        "peak_observed_rss_mib": max(after_load_rss, after_embedding_rss),
        "sample_seconds": sample_seconds,
        "sample_article_count": len(articles),
        "sample_character_count": sum(len(text) for text in texts),
        "embedding_seconds": embedding_seconds,
        "articles_per_second": throughput,
        "vector_dimensions": vector_dimensions,
        "estimated_full_embedding_hours": _ARTICLE_COUNT / throughput / 3600,
        "raw_dense_storage_mib": _ARTICLE_COUNT * vector_dimensions * 4 / 1024**2,
        "queries": query_results,
    }


def _parse_args(arguments: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--max-seq-length", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--random-count", type=int, default=96)
    parser.add_argument("--targeted-count-per-case", type=int, default=16)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(arguments)
    for field in (
        "threads",
        "max_seq_length",
        "batch_size",
        "random_count",
        "targeted_count_per_case",
        "top_k",
    ):
        if getattr(args, field) < 1:
            parser.error(f"--{field.replace('_', '-')}는 1 이상이어야 합니다")
    return args


def main() -> None:
    print(json.dumps(benchmark(_parse_args()), ensure_ascii=False))


if __name__ == "__main__":
    main()
