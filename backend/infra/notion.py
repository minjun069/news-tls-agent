"""공식 Notion SDK 기반 브리핑 페이지 저장 어댑터."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from notion_client import Client

from core.models import NotionPage

_NOTION_BATCH_SIZE = 100
_RICH_TEXT_CHUNK_SIZE = 2_000


class NotionBriefingPublisher:
    """브리핑 마크다운을 기본 Notion 블록으로 변환해 페이지를 만든다."""

    def __init__(self, token: str, client: Client | None = None) -> None:
        self._client = client or Client(auth=token)

    def publish(self, title: str, markdown: str, parent_page_id: str) -> NotionPage:
        blocks = _markdown_to_blocks(markdown)
        response = self._client.pages.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            properties={
                "title": {
                    "type": "title",
                    "title": _rich_text(title),
                }
            },
            children=blocks[:_NOTION_BATCH_SIZE],
        )
        if not isinstance(response, Mapping):
            raise TypeError("Notion 페이지 생성 응답이 객체가 아닙니다")
        page_id = response.get("id")
        url = response.get("url")
        if not isinstance(page_id, str) or not isinstance(url, str):
            raise TypeError("Notion 페이지 응답에 id 또는 url이 없습니다")
        for batch in _batches(blocks[_NOTION_BATCH_SIZE:], _NOTION_BATCH_SIZE):
            self._client.blocks.children.append(block_id=page_id, children=list(batch))
        return NotionPage(page_id=page_id, url=url)


def _markdown_to_blocks(markdown: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        block_type = "paragraph"
        text = line
        if line.startswith("### "):
            block_type, text = "heading_3", line[4:]
        elif line.startswith("## "):
            block_type, text = "heading_2", line[3:]
        elif line.startswith("# "):
            block_type, text = "heading_1", line[2:]
        elif line.startswith("- "):
            block_type, text = "bulleted_list_item", line[2:]
        blocks.append(
            {
                "object": "block",
                "type": block_type,
                block_type: {"rich_text": _rich_text(_plain_markdown(text))},
            }
        )
    return blocks


def _rich_text(value: str) -> list[dict[str, object]]:
    text = value or " "
    return [
        {"type": "text", "text": {"content": text[index : index + _RICH_TEXT_CHUNK_SIZE]}}
        for index in range(0, len(text), _RICH_TEXT_CHUNK_SIZE)
    ]


def _plain_markdown(value: str) -> str:
    linked = re.sub(r"\[([^]]+)]\(([^)]+)\)", r"\1 — \2", value)
    return linked.replace("**", "").replace("`", "")


def _batches(items: Sequence[Any], size: int) -> list[Sequence[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
