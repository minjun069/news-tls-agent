#!/usr/bin/env python3
"""계약을 가진 코드와 문서의 동반 변경을 검사한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_FILE = ROOT / ".harness" / "doc-routes.json"

REVIEW_FILE = ROOT / ".harness" / "doc-review.json"
REVIEW_METADATA_PATH = ".harness/doc-review.json"


def git(*args: str) -> list[str]:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def main_ref() -> str | None:
    for candidate in ("main", "origin/main"):
        if git("rev-parse", "--verify", candidate):
            return candidate
    return None


def compare_base() -> str | None:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    ref = main_ref()
    if not branch or not ref or branch[0] == "main":
        return None
    base = git("merge-base", ref, "HEAD")
    return base[0] if base else None


def changed_files(base: str | None) -> set[str]:
    files: set[str] = set()
    if base:
        files.update(git("diff", "--name-only", f"{base}..HEAD"))
    files.update(git("diff", "--name-only", "HEAD"))
    files.update(git("ls-files", "--others", "--exclude-standard"))
    return files


def to_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(f"^{''.join(out)}$")


def load_routes() -> list[dict[str, object]]:
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))["routes"]


def route_hits(route: dict[str, object], files: set[str]) -> list[str]:
    patterns = [to_regex(str(item)) for item in route["paths"]]
    return sorted(
        file
        for file in files
        if file != REVIEW_METADATA_PATH and any(pattern.match(file) for pattern in patterns)
    )


def file_fingerprints(paths: list[str], root: Path = ROOT) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for relative_path in paths:
        path = root / relative_path
        fingerprints[relative_path] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "<deleted>"
        )
    return fingerprints


def load_reviews() -> dict[str, object]:
    if not REVIEW_FILE.is_file():
        return {}
    data = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    reviews = data.get("reviews", {})
    return reviews if isinstance(reviews, dict) else {}


def review_matches(
    route_name: str,
    hits: list[str],
    reviews: dict[str, object],
    root: Path = ROOT,
) -> bool:
    review = reviews.get(route_name)
    if not isinstance(review, dict):
        return False
    reason = review.get("reason")
    recorded_files = review.get("files")
    return (
        isinstance(reason, str)
        and bool(reason.strip())
        and recorded_files == file_fingerprints(hits, root)
    )


def stale_routes(files: set[str]) -> list[tuple[dict[str, object], list[str]]]:
    stale: list[tuple[dict[str, object], list[str]]] = []
    for route in load_routes():
        hits = route_hits(route, files)
        docs = [str(doc) for doc in route["docs"]]
        if hits and not all(doc in files for doc in docs):
            stale.append((route, hits))
    return stale


def validate_map() -> list[str]:
    problems: list[str] = []
    for route in load_routes():
        name = route.get("name", "이름 없음")
        paths = route.get("paths", [])
        docs = route.get("docs", [])
        if not paths or not docs:
            problems.append(f"{name}: paths 또는 docs가 비어 있습니다")
        for doc in docs:
            if not (ROOT / doc).is_file():
                problems.append(f"{name}: 문서 없음 — {doc}")
    return problems


def acknowledge_no_contract_change(reason: str, files: set[str]) -> int:
    reason = reason.strip()
    if not reason:
        print("[doc-ack] 계약이 유지되는 구체적 근거를 입력해야 합니다")
        return 2

    stale = stale_routes(files)
    if not stale:
        print("[doc-ack] 문서 변경 또는 검토 확인이 필요한 계약 코드가 없습니다")
        return 1

    reviews = load_reviews()
    for route, hits in stale:
        route_name = str(route["name"])
        reviews[route_name] = {
            "files": file_fingerprints(hits),
            "reason": reason,
        }
        print(f"[doc-ack] 기록 완료 — {route_name}")
        for hit in hits:
            print(f"  - {hit}")

    payload = {"version": 1, "reviews": dict(sorted(reviews.items()))}
    REVIEW_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-map", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--acknowledge-no-contract-change", metavar="REASON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.validate_map:
        problems = validate_map()
        if problems:
            print("[doc-map] 라우팅 오류")
            print("\n".join(f"  - {item}" for item in problems))
            return 1
        print("doc-routes.json 유효")
        return 0

    base = compare_base()
    files = changed_files(base)
    if args.acknowledge_no_contract_change is not None:
        return acknowledge_no_contract_change(args.acknowledge_no_contract_change, files)

    reviews = load_reviews()
    unresolved: list[tuple[dict[str, object], list[str]]] = []
    acknowledged: list[str] = []
    for route, hits in stale_routes(files):
        route_name = str(route["name"])
        if review_matches(route_name, hits, reviews):
            acknowledged.append(route_name)
        else:
            unresolved.append((route, hits))

    if unresolved:
        print("[doc-sync] 계약 문서 변경 또는 변경 없음 검토 확인이 필요합니다")
        for route, hits in unresolved:
            docs = ", ".join(str(doc) for doc in route["docs"])
            print(f"\n  라우팅: {route['name']}")
            print(f"  필요한 문서: {docs}")
            for hit in hits[:8]:
                print(f"    - {hit}")
        print("\n  계약이 그대로라면:")
        print("    make doc-ack REASON='입력·출력·외부 동작이 유지되는 구체적 근거'")
        return 1

    if args.verbose:
        scope = f"{base[:8]}..HEAD + 작업 트리" if base else "HEAD + 작업 트리"
        print(f"문서 동기화 OK — {scope}, 변경 {len(files)}개")
        for route_name in acknowledged:
            print(f"  변경 없음 확인 유효 — {route_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
