from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "check_doc_sync",
    ROOT / ".harness" / "check_doc_sync.py",
)
assert SPEC is not None
assert SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def review_for(path: str, root: Path, reason: str = "입출력 계약은 그대로다") -> dict:
    return {
        "route": {
            "files": CHECKER.file_fingerprints([path], root),
            "reason": reason,
        }
    }


def test_review_matches_current_file_hash(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("before\n", encoding="utf-8")
    reviews = review_for("sample.py", tmp_path)

    assert CHECKER.review_matches("route", ["sample.py"], reviews, tmp_path)


def test_review_is_invalid_after_file_changes(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("before\n", encoding="utf-8")
    reviews = review_for("sample.py", tmp_path)

    source.write_text("after\n", encoding="utf-8")

    assert not CHECKER.review_matches("route", ["sample.py"], reviews, tmp_path)


def test_review_requires_a_reason(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("content\n", encoding="utf-8")
    reviews = review_for("sample.py", tmp_path, reason="   ")

    assert not CHECKER.review_matches("route", ["sample.py"], reviews, tmp_path)
