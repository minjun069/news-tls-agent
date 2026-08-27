"""실제 MS-SQL에서 Repository 정합성과 트랜잭션을 검증한다."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import Engine, delete, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from core.config import ConfigError, load_mssql_config
from core.models import Article, EventArticleInput, IssueCreate, IssueEventInput
from db.migrate import apply_migrations
from infra.db import create_db_engine, create_session_factory
from infra.entities import ArticleRow, IssueRow
from infra.repository import SqlRepository

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[3]


class RepositoryContext:
    def __init__(
        self,
        repository: SqlRepository,
        session_factory: sessionmaker[Session],
        engine: Engine,
        article_base: int,
        topic_prefix: str,
    ) -> None:
        self.repository = repository
        self.session_factory = session_factory
        self.engine = engine
        self.article_base = article_base
        self.topic_prefix = topic_prefix


@pytest.fixture(scope="module")
def context() -> Iterator[RepositoryContext]:
    load_dotenv(_REPO_ROOT / ".env")
    try:
        config = load_mssql_config(os.environ)
    except ConfigError as exc:
        pytest.skip(f"MS-SQL 설정이 없습니다: {exc}")

    apply_migrations(config)
    engine = create_db_engine(config)
    session_factory = create_session_factory(engine)
    run_id = int(time.time() * 1_000_000)
    article_base = 8_000_000_000_000_000 + run_id
    topic_prefix = f"test-s2-{run_id}"
    context = RepositoryContext(
        SqlRepository(session_factory), session_factory, engine, article_base, topic_prefix
    )
    try:
        yield context
    finally:
        with session_factory.begin() as session:
            session.execute(delete(IssueRow).where(IssueRow.topic.like(f"{topic_prefix}%")))
            session.execute(
                delete(ArticleRow).where(
                    ArticleRow.article_id.between(article_base, article_base + 100)
                )
            )
        engine.dispose()


def article(article_id: int, title: str, service_date: date) -> Article:
    return Article(
        article_id=article_id,
        title=title,
        service_date=service_date,
        content=f"{title} 본문",
    )


def test_schema_has_six_tables_and_seven_contract_indexes(context: RepositoryContext) -> None:
    inspector = inspect(context.engine)
    expected_tables = {
        "articles",
        "issues",
        "issue_events",
        "issue_event_articles",
        "article_entities",
        "article_relations",
    }
    assert expected_tables <= set(inspector.get_table_names(schema="dbo"))
    assert inspector.get_pk_constraint("articles", schema="dbo")["name"] == "PK_articles"

    index_names: set[str] = set()
    for table in expected_tables:
        index_names.update(
            index["name"] for index in inspector.get_indexes(table, schema="dbo") if index["name"]
        )
    assert {
        "IX_articles_service_date",
        "UQ_issues_topic",
        "IX_issue_events_issue_order",
        "IX_iea_article",
        "UQ_entities_article_entity",
        "IX_relations_article",
    } <= index_names


def test_article_upsert_is_idempotent(context: RepositoryContext) -> None:
    repository = context.repository
    article_id = context.article_base

    assert repository.upsert_articles([article(article_id, "처음 제목", date(2026, 1, 1))]) == 1
    assert repository.upsert_articles([article(article_id, "수정 제목", date(2026, 1, 2))]) == 1

    saved = repository.get_article(article_id)
    assert saved is not None
    assert saved.title == "수정 제목"
    assert saved.service_date == date(2026, 1, 2)


def test_three_level_join_reverse_lookup_and_ranking(context: RepositoryContext) -> None:
    repository = context.repository
    ids = [context.article_base + offset for offset in (1, 2, 3)]
    repository.upsert_articles(
        [
            article(ids[0], "먼 기사", date(2026, 1, 1)),
            article(ids[1], "전날 기사", date(2026, 1, 9)),
            article(ids[2], "다음날 기사", date(2026, 1, 11)),
        ]
    )
    issue = IssueCreate(
        topic=f"{context.topic_prefix}-join",
        title="통합 테스트 이슈",
        summary="이슈-이벤트-기사 연결",
        generated_at=datetime.now(UTC),
        events=(
            IssueEventInput(
                event_order=0,
                event_date=date(2026, 1, 10),
                title="대표 이벤트",
                summary=None,
                articles=tuple(
                    EventArticleInput(article_id=article_id, relevance_score=0.9)
                    for article_id in reversed(ids)
                ),
            ),
        ),
    )

    issue_id = repository.save_issue(issue)
    loaded = repository.get_issue(issue_id)

    assert loaded is not None
    assert loaded.events[0].representative_article.article_id == ids[1]
    assert [link.article.article_id for link in loaded.events[0].articles] == ids
    assert repository.find_issue_by_topic(issue.topic) == loaded

    citations = repository.find_issues_by_article(ids[1])
    assert [(citation.issue_id, citation.event_title) for citation in citations] == [
        (issue_id, "대표 이벤트")
    ]

    requested = repository.get_articles([ids[2], 0, ids[0], ids[2]])
    assert [saved.article_id for saved in requested] == [ids[2], ids[0]]


def test_failed_article_link_rolls_back_whole_issue(context: RepositoryContext) -> None:
    repository = context.repository
    existing_id = context.article_base + 10
    repository.upsert_articles([article(existing_id, "존재 기사", date(2026, 2, 1))])
    issue = IssueCreate(
        topic=f"{context.topic_prefix}-rollback",
        title=None,
        summary=None,
        generated_at=datetime.now(UTC),
        events=(
            IssueEventInput(
                event_order=0,
                event_date=date(2026, 2, 1),
                title="롤백 이벤트",
                summary=None,
                articles=(
                    EventArticleInput(article_id=existing_id, relevance_score=1.0),
                    EventArticleInput(article_id=context.article_base + 99, relevance_score=0.5),
                ),
            ),
        ),
    )

    with pytest.raises(IntegrityError):
        repository.save_issue(issue)

    assert repository.find_issue_by_topic(issue.topic) is None
