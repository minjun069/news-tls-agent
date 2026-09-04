"""NFR-04의 키워드·의미·결합 기사 검색 유스케이스."""

from __future__ import annotations

from core.models import (
    ArticleSearchRequest,
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
        normalized_query = SemanticQuery(text=query).text
        request = ArticleSearchRequest(
            method=method,
            options=options,
            keyword_terms=(normalized_query,) if method is not SearchMethod.SEMANTIC else (),
            semantic_text=normalized_query if method is not SearchMethod.KEYWORD else None,
        )
        return self.search_request(request)

    def search_request(self, request: ArticleSearchRequest) -> SearchResult:
        """P3의 키워드 조합과 의미 문장을 손실 없이 실행한다."""
        options = request.options
        if request.method is SearchMethod.KEYWORD:
            hits = self._search_keywords(request)
        elif request.method is SearchMethod.SEMANTIC:
            hits = self._search_semantic(request.semantic_text or "", options)
        else:
            keyword_hits = self._search_keywords(request)
            semantic_hits = self._search_semantic(request.semantic_text or "", options)
            hits = reciprocal_rank_fusion(
                [keyword_hits, semantic_hits],
                top_k=options.top_k,
            )
        return SearchResult(method=request.method, hits=tuple(hits))

    def _search_keywords(self, request: ArticleSearchRequest) -> list[SearchHit]:
        options = request.options
        keyword_query = KeywordQuery(
            terms=request.keyword_terms,
            operator=request.keyword_operator,
            top_k=options.top_k,
            date_from=options.date_from,
            date_to=options.date_to,
        )
        return self._keyword_searcher.search_keywords(keyword_query)

    def _search_semantic(self, query: str, options: SearchOptions) -> list[SearchHit]:
        semantic_query = SemanticQuery(
            text=query,
            top_k=options.top_k,
            date_from=options.date_from,
            date_to=options.date_to,
        )
        vector = self._embedding_provider.embed_query(semantic_query.text)
        return self._vector_store.search_vector(vector, semantic_query)
