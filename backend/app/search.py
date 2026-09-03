"""NFR-04의 키워드·의미·결합 기사 검색 유스케이스."""

from __future__ import annotations

from core.models import (
    KeywordQuery,
    SearchHit,
    SearchMethod,
    SearchOptions,
    SearchResult,
    SemanticQuery,
)
from core.ports import EmbeddingProvider, KeywordSearcher, VectorStore
from core.ranking import reciprocal_rank_fusion


class ArticleSearchService:
    """검색 방식 선택을 저장소 어댑터와 분리해 실행한다."""

    def __init__(
        self,
        keyword_searcher: KeywordSearcher,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._keyword_searcher = keyword_searcher
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider

    def search(
        self,
        query: str,
        method: SearchMethod,
        options: SearchOptions,
    ) -> SearchResult:
        """선택한 방식으로 검색하고 방식과 순위를 함께 반환한다."""
        keyword_query = KeywordQuery(
            terms=(query,),
            top_k=options.top_k,
            date_from=options.date_from,
            date_to=options.date_to,
        )
        if method is SearchMethod.KEYWORD:
            hits = self._keyword_searcher.search_keywords(keyword_query)
        elif method is SearchMethod.SEMANTIC:
            hits = self._search_semantic(query, options)
        else:
            keyword_hits = self._keyword_searcher.search_keywords(keyword_query)
            semantic_hits = self._search_semantic(query, options)
            hits = reciprocal_rank_fusion(
                [keyword_hits, semantic_hits],
                top_k=options.top_k,
            )
        return SearchResult(method=method, hits=tuple(hits))

    def _search_semantic(self, query: str, options: SearchOptions) -> list[SearchHit]:
        semantic_query = SemanticQuery(
            text=query,
            top_k=options.top_k,
            date_from=options.date_from,
            date_to=options.date_to,
        )
        vector = self._embedding_provider.embed_query(semantic_query.text)
        return self._vector_store.search_vector(vector, semantic_query)
