"""MS-SQL Repository 구현 — 애플리케이션 SQL은 이 모듈에만 둔다."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from core.models import (
    Article,
    EventArticle,
    IssueCitation,
    IssueCreate,
    IssueDetail,
    IssueEvent,
)
from core.ranking import choose_representative
from infra.entities import (
    ArticleRow,
    IssueEventArticleRow,
    IssueEventRow,
    IssueRow,
)

_UPSERT_ARTICLE_SQL = text(
    """
    MERGE dbo.articles AS target
    USING (
        SELECT
            :article_id AS article_id,
            :title AS title,
            :sub_title AS sub_title,
            :service_date AS service_date,
            :summary AS summary,
            :content AS content,
            :url AS url,
            :category_large AS category_large,
            :category_middle AS category_middle,
            :category_small AS category_small,
            :entities_extracted_at AS entities_extracted_at
    ) AS source
    ON target.article_id = source.article_id
    WHEN MATCHED THEN UPDATE SET
        title = source.title,
        sub_title = source.sub_title,
        service_date = source.service_date,
        summary = source.summary,
        content = source.content,
        url = source.url,
        category_large = source.category_large,
        category_middle = source.category_middle,
        category_small = source.category_small,
        entities_extracted_at = source.entities_extracted_at
    WHEN NOT MATCHED THEN INSERT (
        article_id, title, sub_title, service_date, summary, content, url,
        category_large, category_middle, category_small, entities_extracted_at
    ) VALUES (
        source.article_id, source.title, source.sub_title, source.service_date,
        source.summary, source.content, source.url, source.category_large,
        source.category_middle, source.category_small, source.entities_extracted_at
    );
    """
)


def _to_article(row: ArticleRow) -> Article:
    return Article.model_validate(row)


class SqlRepository:
    """세션 팩토리를 주입받는 MS-SQL 저장소."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_articles(self, articles: Sequence[Article]) -> int:
        if not articles:
            return 0
        payloads = [article.model_dump() for article in articles]
        with self._session_factory.begin() as session:
            session.execute(_UPSERT_ARTICLE_SQL, payloads)
        return len(payloads)

    def get_article(self, article_id: int) -> Article | None:
        with self._session_factory() as session:
            row = session.get(ArticleRow, article_id)
            return _to_article(row) if row is not None else None

    def get_articles(self, article_ids: Sequence[int]) -> list[Article]:
        if not article_ids:
            return []
        unique_ids = list(dict.fromkeys(article_ids))
        with self._session_factory() as session:
            rows = session.scalars(
                select(ArticleRow).where(ArticleRow.article_id.in_(unique_ids))
            ).all()
        by_id = {row.article_id: _to_article(row) for row in rows}
        return [by_id[article_id] for article_id in unique_ids if article_id in by_id]

    def save_issue(self, issue: IssueCreate) -> int:
        """세 테이블 저장 중 하나라도 실패하면 전체를 롤백한다."""
        with self._session_factory.begin() as session:
            issue_row = IssueRow(
                topic=issue.topic,
                title=issue.title,
                summary=issue.summary,
                generated_at=issue.generated_at,
            )
            session.add(issue_row)
            session.flush()

            for event in issue.events:
                event_row = IssueEventRow(
                    issue_id=issue_row.issue_id,
                    event_order=event.event_order,
                    event_date=event.event_date,
                    title=event.title,
                    summary=event.summary,
                )
                session.add(event_row)
                session.flush()
                session.add_all(
                    IssueEventArticleRow(
                        event_id=event_row.event_id,
                        article_id=link.article_id,
                        relevance_score=link.relevance_score,
                    )
                    for link in event.articles
                )

            session.flush()
            return issue_row.issue_id

    def get_issue(self, issue_id: int) -> IssueDetail | None:
        with self._session_factory() as session:
            issue_row = session.get(IssueRow, issue_id)
            return self._build_issue(session, issue_row) if issue_row is not None else None

    def find_issue_by_topic(self, topic: str) -> IssueDetail | None:
        with self._session_factory() as session:
            issue_row = session.scalar(select(IssueRow).where(IssueRow.topic == topic))
            return self._build_issue(session, issue_row) if issue_row is not None else None

    def find_issues_by_article(self, article_id: int) -> list[IssueCitation]:
        statement = (
            select(IssueRow, IssueEventRow)
            .join(IssueEventRow, IssueEventRow.issue_id == IssueRow.issue_id)
            .join(
                IssueEventArticleRow,
                IssueEventArticleRow.event_id == IssueEventRow.event_id,
            )
            .where(IssueEventArticleRow.article_id == article_id)
            .order_by(IssueEventRow.event_date, IssueRow.issue_id, IssueEventRow.event_id)
        )
        with self._session_factory() as session:
            rows = session.execute(statement).all()
        return [
            IssueCitation(
                issue_id=issue_row.issue_id,
                topic=issue_row.topic,
                event_id=event_row.event_id,
                event_date=event_row.event_date,
                event_title=event_row.title,
            )
            for issue_row, event_row in rows
        ]

    @staticmethod
    def _build_issue(session: Session, issue_row: IssueRow) -> IssueDetail:
        event_rows = session.scalars(
            select(IssueEventRow)
            .where(IssueEventRow.issue_id == issue_row.issue_id)
            .order_by(IssueEventRow.event_order, IssueEventRow.event_id)
        ).all()
        events = tuple(SqlRepository._build_event(session, row) for row in event_rows)
        return IssueDetail(
            issue_id=issue_row.issue_id,
            topic=issue_row.topic,
            title=issue_row.title,
            summary=issue_row.summary,
            generated_at=issue_row.generated_at,
            events=events,
        )

    @staticmethod
    def _build_event(session: Session, event_row: IssueEventRow) -> IssueEvent:
        rows = session.execute(
            select(IssueEventArticleRow, ArticleRow)
            .join(ArticleRow, ArticleRow.article_id == IssueEventArticleRow.article_id)
            .where(IssueEventArticleRow.event_id == event_row.event_id)
            .order_by(IssueEventArticleRow.article_id)
        ).all()
        articles = tuple(
            EventArticle(article=_to_article(article_row), relevance_score=link.relevance_score)
            for link, article_row in rows
        )
        representative = choose_representative(articles, event_row.event_date)
        return IssueEvent(
            event_id=event_row.event_id,
            event_order=event_row.event_order,
            event_date=event_row.event_date,
            title=event_row.title,
            summary=event_row.summary,
            articles=articles,
            representative_article=representative,
        )
