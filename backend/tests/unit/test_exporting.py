from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.exporting import BriefingExportService, build_briefing_markdown
from core.errors import ExportNotConfiguredError
from core.models import Article, EventArticle, IssueDetail, IssueEvent, NotionPage


def make_issue() -> IssueDetail:
    article = Article(
        article_id=101,
        title="근거 기사",
        service_date=date(2026, 9, 1),
        content="본문",
        url="https://example.com/101",
    )
    link = EventArticle(article=article, relevance_score=0.9)
    events = tuple(
        IssueEvent(
            event_id=index,
            event_order=index,
            event_date=date(2026, 9, index),
            title=f"사건 {index}",
            summary=f"사건 {index} 설명",
            articles=(link,),
            representative_article=article,
        )
        for index in (1, 2)
    )
    return IssueDetail(
        issue_id=7,
        topic="내보내기 테스트",
        title="테스트 브리핑",
        summary="요약입니다.",
        generated_at=datetime(2026, 9, 4, tzinfo=UTC),
        events=events,
    )


class FakeRepository:
    def __init__(self) -> None:
        self.issue = make_issue()

    def get_issue(self, issue_id: int):
        return self.issue if issue_id == 7 else None


class FakePdfRenderer:
    def __init__(self) -> None:
        self.markdown = ""
        self.output_path = ""

    def render(self, markdown: str, output_path: str) -> None:
        self.markdown = markdown
        self.output_path = output_path
        Path(output_path).write_bytes(b"%PDF-fake")


class FakeNotionPublisher:
    def __init__(self) -> None:
        self.parent_page_id = ""

    def publish(self, title: str, markdown: str, parent_page_id: str) -> NotionPage:
        assert title == "테스트 브리핑"
        assert "기사 #101" in markdown
        self.parent_page_id = parent_page_id
        return NotionPage(page_id="page-1", url="https://notion.so/page-1")


def test_markdown_contains_whole_issue_and_traceable_articles() -> None:
    markdown = build_briefing_markdown(make_issue())

    assert "# 테스트 브리핑" in markdown
    assert "### 2026-09-01 · 사건 1" in markdown
    assert "### 2026-09-02 · 사건 2" in markdown
    assert "기사 #101" in markdown
    assert "https://example.com/101" in markdown


def test_pdf_and_notion_share_the_same_briefing_service(tmp_path: Path) -> None:
    renderer = FakePdfRenderer()
    notion = FakeNotionPublisher()
    service = BriefingExportService(
        FakeRepository(),
        renderer,
        tmp_path,
        notion_publisher=notion,
        default_notion_parent_page_id="default-parent",
    )

    pdf = service.export_briefing(7, "pdf")
    notion_result = service.export_briefing(7, "notion")

    assert pdf["download_url"].startswith("/downloads/")
    assert Path(renderer.output_path).read_bytes().startswith(b"%PDF")
    assert notion_result["url"] == "https://notion.so/page-1"
    assert notion.parent_page_id == "default-parent"


def test_notion_requires_token_adapter_and_parent_page(tmp_path: Path) -> None:
    service = BriefingExportService(FakeRepository(), FakePdfRenderer(), tmp_path)

    with pytest.raises(ExportNotConfiguredError, match="Notion 연결"):
        service.export_briefing(7, "notion")
