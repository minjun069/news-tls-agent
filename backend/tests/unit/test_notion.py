from __future__ import annotations

from infra.notion import NotionBriefingPublisher, _markdown_to_blocks


class FakePages:
    def __init__(self) -> None:
        self.arguments = None

    def create(self, **kwargs):
        self.arguments = kwargs
        return {"id": "page-id", "url": "https://notion.so/page-id"}


class FakeChildren:
    def __init__(self) -> None:
        self.calls = []

    def append(self, **kwargs):
        self.calls.append(kwargs)


class FakeClient:
    def __init__(self) -> None:
        self.pages = FakePages()
        self.blocks = type("Blocks", (), {"children": FakeChildren()})()


def test_markdown_is_converted_to_notion_headings_and_evidence_bullets() -> None:
    blocks = _markdown_to_blocks("# 제목\n\n## 요약\n본문\n- [기사](https://example.com)")

    assert [block["type"] for block in blocks] == [
        "heading_1",
        "heading_2",
        "paragraph",
        "bulleted_list_item",
    ]
    rich_text = blocks[-1]["bulleted_list_item"]["rich_text"]
    assert rich_text[0]["text"]["content"] == "기사 — https://example.com"


def test_publisher_creates_page_under_requested_parent() -> None:
    client = FakeClient()
    publisher = NotionBriefingPublisher("test-token", client=client)

    page = publisher.publish("브리핑", "# 브리핑\n\n본문", "parent-id")

    assert page.page_id == "page-id"
    assert client.pages.arguments["parent"]["page_id"] == "parent-id"
