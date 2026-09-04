"""화면 메뉴와 MCP 도구가 공유하는 브리핑 내보내기 유스케이스."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from core.errors import BriefingExportError, ExportNotConfiguredError, IssueNotFoundError
from core.models import ExportFormat, IssueDetail
from core.ports import NotionPublisher, PdfRenderer, Repository


class BriefingExportService:
    """이슈 전체를 한 번 마크다운으로 구성한 뒤 요청 형식으로 변환한다."""

    def __init__(
        self,
        repository: Repository,
        pdf_renderer: PdfRenderer,
        download_dir: Path,
        *,
        notion_publisher: NotionPublisher | None = None,
        default_notion_parent_page_id: str = "",
    ) -> None:
        self._repository = repository
        self._pdf_renderer = pdf_renderer
        self._download_dir = download_dir
        self._notion_publisher = notion_publisher
        self._default_notion_parent_page_id = default_notion_parent_page_id.strip()

    def export_briefing(
        self,
        issue_id: int,
        output_format: Literal["pdf", "notion"],
        parent_page_id: str | None = None,
    ) -> dict[str, object]:
        issue = self._repository.get_issue(issue_id)
        if issue is None:
            raise IssueNotFoundError(f"이슈를 찾을 수 없습니다: {issue_id}")
        export_format = ExportFormat(output_format)
        title = issue.title or issue.topic
        markdown = build_briefing_markdown(issue)

        if export_format is ExportFormat.PDF:
            return self._export_pdf(issue, markdown)

        resolved_parent = (parent_page_id or self._default_notion_parent_page_id).strip()
        if self._notion_publisher is None or not resolved_parent:
            raise ExportNotConfiguredError("Notion 연결 설정이 필요합니다.")
        try:
            page = self._notion_publisher.publish(title, markdown, resolved_parent)
        except ExportNotConfiguredError:
            raise
        except Exception as exc:
            raise BriefingExportError("Notion 페이지를 생성하지 못했습니다.") from exc
        return {
            "format": export_format.value,
            "page_id": page.page_id,
            "url": page.url,
            "message": "Notion 페이지를 생성했습니다.",
        }

    def _export_pdf(self, issue: IssueDetail, markdown: str) -> dict[str, object]:
        self._download_dir.mkdir(parents=True, exist_ok=True)
        display_title = issue.title or issue.topic
        file_name = f"{issue.issue_id}_{_safe_file_stem(display_title)}_타임라인.pdf"
        output_path = self._download_dir / file_name
        try:
            self._pdf_renderer.render(markdown, str(output_path))
        except ExportNotConfiguredError:
            raise
        except Exception as exc:
            raise BriefingExportError("PDF를 생성하지 못했습니다.") from exc
        return {
            "format": ExportFormat.PDF.value,
            "file_name": file_name,
            "download_url": f"/downloads/{quote(file_name)}",
            "message": "PDF를 생성했습니다.",
        }


def build_briefing_markdown(issue: IssueDetail) -> str:
    """이슈 요약·타임라인·모든 근거 기사를 추적 가능한 마크다운으로 만든다."""
    title = issue.title or issue.topic
    lines = [
        f"# {title}",
        "",
        f"- 주제: {issue.topic}",
        f"- 생성 시각: {issue.generated_at.isoformat()}",
        "",
        "## 이슈 요약",
        "",
        issue.summary or "요약이 없습니다.",
        "",
        "## 사건 타임라인",
    ]
    for event in issue.events:
        lines.extend(
            [
                "",
                f"### {event.event_date.isoformat()} · {event.title}",
                "",
                event.summary or "설명이 없습니다.",
                "",
                "근거 기사",
            ]
        )
        representative_id = event.representative_article.article_id
        for link in event.articles:
            article = link.article
            label = (
                f"{article.title} (기사 #{article.article_id}, {article.service_date.isoformat()})"
            )
            if article.article_id == representative_id:
                label += " · 대표 기사"
            if article.url:
                lines.append(f"- [{label}]({article.url})")
            else:
                lines.append(f"- {label}")
    return "\n".join(lines).strip() + "\n"


def _safe_file_stem(value: str) -> str:
    normalized = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value.strip())
    normalized = re.sub(r"\s+", "_", normalized).strip("._")
    return (normalized or "issue")[:80]


def resolve_download_dir(configured_path: str, repository_root: Path) -> Path:
    """상대 설정은 프로젝트 루트 기준으로 해석해 API와 MCP가 같은 위치를 쓰게 한다."""
    path = Path(configured_path)
    return path if path.is_absolute() else repository_root / path
