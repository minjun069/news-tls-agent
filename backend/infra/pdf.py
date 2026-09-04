"""fpdf2 기반 한글 브리핑 PDF 어댑터."""

from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from core.errors import ExportNotConfiguredError

_DEFAULT_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"),
    Path("/mnt/c/Windows/Fonts/malgun.ttf"),
)


class FpdfBriefingRenderer:
    """마크다운의 제목·목록·본문을 읽기 좋은 PDF로 변환한다."""

    def __init__(self, font_path: str = "") -> None:
        self._configured_font_path = font_path.strip()

    def render(self, markdown: str, output_path: str) -> None:
        font_path = self._resolve_font_path()
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            pdf = FPDF(format="A4")
            pdf.set_margins(18, 18, 18)
            pdf.set_auto_page_break(auto=True, margin=18)
            pdf.add_font("NewsSans", fname=str(font_path))
            pdf.add_page()
            for line in markdown.splitlines():
                self._write_line(pdf, line)
            pdf.output(str(temporary))
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _resolve_font_path(self) -> Path:
        if self._configured_font_path:
            configured = Path(self._configured_font_path).expanduser()
            if configured.is_file():
                return configured
            raise ExportNotConfiguredError(
                f"PDF_FONT_PATH의 글꼴 파일을 찾을 수 없습니다: {configured}"
            )
        for candidate in _DEFAULT_FONT_CANDIDATES:
            if candidate.is_file():
                return candidate
        raise ExportNotConfiguredError(
            "한글 PDF 글꼴이 없습니다. PDF_FONT_PATH에 TTF 글꼴 경로를 설정해 주세요."
        )

    @staticmethod
    def _write_line(pdf: FPDF, raw_line: str) -> None:
        stripped = raw_line.strip()
        if not stripped:
            pdf.ln(3)
            return
        if stripped.startswith("# "):
            size, height, text = 22, 11, stripped[2:]
        elif stripped.startswith("## "):
            size, height, text = 16, 9, stripped[3:]
        elif stripped.startswith("### "):
            size, height, text = 13, 8, stripped[4:]
        elif stripped.startswith("- "):
            size, height, text = 10, 6.5, f"• {stripped[2:]}"
        else:
            size, height, text = 10, 6.5, stripped
        pdf.set_font("NewsSans", size=size)
        pdf.multi_cell(
            0,
            height,
            text=_plain_markdown(text),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )


def _plain_markdown(value: str) -> str:
    linked = re.sub(r"\[([^]]+)]\(([^)]+)\)", r"\1 — \2", value)
    return linked.replace("**", "").replace("`", "")
