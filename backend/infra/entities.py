"""ERD의 6개 MS-SQL 테이블에 대한 SQLAlchemy 매핑."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Unicode,
    UnicodeText,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ArticleRow(Base):
    __tablename__ = "articles"
    __table_args__ = (Index("IX_articles_service_date", "service_date"),)

    article_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Unicode(500), nullable=False)
    sub_title: Mapped[str | None] = mapped_column(Unicode(500))
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str | None] = mapped_column(UnicodeText)
    content: Mapped[str | None] = mapped_column(UnicodeText)
    url: Mapped[str | None] = mapped_column(Unicode(1000))
    category_large: Mapped[str | None] = mapped_column(Unicode(100))
    category_middle: Mapped[str | None] = mapped_column(Unicode(100))
    category_small: Mapped[str | None] = mapped_column(Unicode(100))
    entities_extracted_at: Mapped[datetime | None] = mapped_column(DateTime)


class ArticleEntityRow(Base):
    __tablename__ = "article_entities"
    __table_args__ = (
        UniqueConstraint("article_id", "entity_id", name="UQ_entities_article_entity"),
    )

    entity_id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("articles.article_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Unicode(300), nullable=False)
    entity_type: Mapped[str] = mapped_column(Unicode(50), nullable=False)


class ArticleRelationRow(Base):
    __tablename__ = "article_relations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["article_id", "source_entity_id"],
            ["article_entities.article_id", "article_entities.entity_id"],
            name="FK_article_relations_source",
        ),
        ForeignKeyConstraint(
            ["article_id", "target_entity_id"],
            ["article_entities.article_id", "article_entities.entity_id"],
            name="FK_article_relations_target",
        ),
        Index("IX_relations_article", "article_id"),
    )

    relation_id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("articles.article_id", ondelete="CASCADE"), nullable=False
    )
    source_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_type: Mapped[str] = mapped_column(Unicode(100), nullable=False)


class IssueRow(Base):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("topic", name="UQ_issues_topic"),)

    issue_id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    topic: Mapped[str] = mapped_column(Unicode(500), nullable=False)
    title: Mapped[str | None] = mapped_column(Unicode(500))
    summary: Mapped[str | None] = mapped_column(UnicodeText)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class IssueEventRow(Base):
    __tablename__ = "issue_events"
    __table_args__ = (Index("IX_issue_events_issue_order", "issue_id", "event_order"),)

    event_id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issues.issue_id", ondelete="CASCADE"), nullable=False
    )
    event_order: Mapped[int] = mapped_column(Integer, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(Unicode(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(UnicodeText)


class IssueEventArticleRow(Base):
    __tablename__ = "issue_event_articles"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "article_id", name="PK_issue_event_articles"),
        Index("IX_iea_article", "article_id"),
    )

    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issue_events.event_id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("articles.article_id"), nullable=False
    )
    relevance_score: Mapped[float | None] = mapped_column(Float(53))
