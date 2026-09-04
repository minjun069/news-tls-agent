"""HTTP 라우터 공통 SSE 직렬화."""

from __future__ import annotations

import json
from collections.abc import Mapping


def encode_sse(event: str, data: Mapping[str, object]) -> str:
    """한 이벤트를 브라우저 EventSource가 읽는 SSE 프레임으로 만든다."""
    payload = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"
