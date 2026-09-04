from __future__ import annotations

from datetime import UTC, date, datetime

from core.models import (
    Article,
    EventArticle,
    IssueDetail,
    IssueEvent,
    IssueSummary,
    SearchHit,
    SearchMethod,
    SearchResult,
)
from mcp_server.tools.payloads import (
    ARTICLE_CONTENT_LIMIT,
    export_briefing_payload,
    get_issue_payload,
    list_issues_payload,
    read_article_payload,
    search_articles_payload,
)


def make_article(article_id: int, *, content: str = "본문") -> Article:
    return Article(
        article_id=article_id,
        title=f"기사 {article_id}",
        sub_title=None,
        service_date=date(2025, 4, article_id),
        summary=f"요약 {article_id}",
        content=content,
        url=f"https://example.com/{article_id}",
    )


def make_issue(article: Article) -> IssueDetail:
    link = EventArticle(article=article, relevance_score=0.9)
    event = IssueEvent(
        event_id=11,
        event_order=1,
        event_date=article.service_date,
        title="주요 사건",
        summary="사건 요약",
        articles=(link,),
        representative_article=article,
    )
    return IssueDetail(
        issue_id=7,
        topic="테스트 토픽",
        title=None,
        summary="이슈 요약",
        generated_at=datetime(2026, 8, 21, 14, 23, 11, tzinfo=UTC),
        events=(event,),
    )


class FakeRepository:
    def __init__(self) -> None:
        self.articles = {1: make_article(1), 2: make_article(2)}
        self.issue = make_issue(self.articles[1])
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("database offline")

    def get_articles(self, article_ids):
        self._check()
        return [self.articles[item] for item in article_ids if item in self.articles]

    def get_article(self, article_id: int):
        self._check()
        return self.articles.get(article_id)

    def list_issues(self):
        self._check()
        return [
            IssueSummary(
                issue_id=self.issue.issue_id,
                topic=self.issue.topic,
                title=self.issue.title,
                generated_at=self.issue.generated_at,
                event_count=len(self.issue.events),
            )
        ]

    def get_issue(self, issue_id: int):
        self._check()
        return self.issue if issue_id == self.issue.issue_id else None


class FakeSearcher:
    def __init__(self) -> None:
        self.calls = []

    def search(self, query, method, options):
        self.calls.append((query, method, options))
        return SearchResult(
            method=method,
            hits=(
                SearchHit(article_id=2, score=0.9),
                SearchHit(article_id=99, score=0.8),
                SearchHit(article_id=1, score=0.7),
            ),
        )


class FakeExporter:
    def export_briefing(self, issue_id, output_format, parent_page_id):
        assert issue_id == 7
        assert output_format == "pdf"
        assert parent_page_id is None
        return {
            "format": "pdf",
            "file_name": "briefing.pdf",
            "download_url": "/downloads/briefing.pdf",
            "message": "PDF를 생성했습니다.",
        }


def test_search_payload_returns_existing_articles_in_rank_order() -> None:
    repository = FakeRepository()
    searcher = FakeSearcher()

    payload = search_articles_payload(
        searcher,
        repository,
        query="탄핵",
        method="keyword",
        top_k=3,
        date_from=date(2025, 1, 1),
        date_to=date(2025, 4, 4),
    )

    assert payload["ok"] is True
    assert payload["method"] == "keyword"
    assert [item["article_id"] for item in payload["articles"]] == [2, 1]
    assert "content" not in payload["articles"][0]
    assert searcher.calls[0][1] is SearchMethod.KEYWORD


def test_search_payload_rejects_invalid_method_and_date_range() -> None:
    repository = FakeRepository()
    searcher = FakeSearcher()

    invalid_method = search_articles_payload(searcher, repository, query="탄핵", method="unknown")
    invalid_dates = search_articles_payload(
        searcher,
        repository,
        query="탄핵",
        date_from=date(2025, 2, 1),
        date_to=date(2025, 1, 1),
    )

    assert invalid_method["error"]["code"] == "INVALID_ARGUMENT"
    assert invalid_dates["error"]["code"] == "INVALID_ARGUMENT"
    assert searcher.calls == []


def test_read_article_reports_truncation_and_missing_article() -> None:
    repository = FakeRepository()
    repository.articles[1] = make_article(1, content="가" * (ARTICLE_CONTENT_LIMIT + 1))

    found = read_article_payload(repository, 1)
    missing = read_article_payload(repository, 999)

    assert found["article"]["truncated"] is True
    assert len(found["article"]["content"]) == ARTICLE_CONTENT_LIMIT
    assert found["article"]["summary"] == "요약 1"
    assert "일부만" in found["message"]
    assert missing == {
        "ok": False,
        "error": {
            "code": "ARTICLE_NOT_FOUND",
            "message": "해당 기사를 찾을 수 없습니다.",
        },
    }


def test_list_and_get_issue_payloads_match_contract() -> None:
    repository = FakeRepository()

    listed = list_issues_payload(repository)
    detail = get_issue_payload(repository, 7)

    assert listed["issues"] == [
        {
            "issue_id": 7,
            "topic": "테스트 토픽",
            "title": "테스트 토픽",
            "generated_at": "2026-08-21T14:23:11+00:00",
            "event_count": 1,
        }
    ]
    event = detail["issue"]["events"][0]
    assert event["primary_article"]["article_id"] == 1
    assert event["articles"] == [
        {
            "article_id": 1,
            "title": "기사 1",
            "service_date": "2025-04-01",
            "relevance_score": 0.9,
        }
    ]
    assert detail["issue"]["generated_at"] == "2026-08-21T14:23:11+00:00"
    assert get_issue_payload(repository, 99)["error"]["code"] == "ISSUE_NOT_FOUND"


def test_storage_failure_uses_structured_error_instead_of_raising() -> None:
    repository = FakeRepository()
    repository.fail = True

    payload = list_issues_payload(repository)

    assert payload == {
        "ok": False,
        "error": {
            "code": "STORAGE_UNAVAILABLE",
            "message": "저장소에 연결할 수 없습니다.",
        },
    }


def test_export_payload_is_explicitly_unconfigured_until_exporter_is_injected() -> None:
    repository = FakeRepository()

    unconfigured = export_briefing_payload(
        repository,
        None,
        issue_id=7,
        output_format="pdf",
    )
    configured = export_briefing_payload(
        repository,
        FakeExporter(),
        issue_id=7,
        output_format="pdf",
    )

    assert unconfigured["error"]["code"] == "EXPORT_NOT_CONFIGURED"
    assert configured == {
        "ok": True,
        "format": "pdf",
        "file_name": "briefing.pdf",
        "download_url": "/downloads/briefing.pdf",
        "message": "PDF를 생성했습니다.",
    }
    assert (
        export_briefing_payload(
            repository,
            FakeExporter(),
            issue_id=99,
            output_format="pdf",
        )["error"]["code"]
        == "ISSUE_NOT_FOUND"
    )
    assert (
        export_briefing_payload(
            repository,
            FakeExporter(),
            issue_id=7,
            output_format="html",
        )["error"]["code"]
        == "INVALID_ARGUMENT"
    )
