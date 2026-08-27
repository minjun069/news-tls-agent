-- 현재 전체 DDL 참고본. 실행 원본은 migrations/이며 이 파일을 직접 실행하지 않는다.
-- schema_migrations는 000_bootstrap.sql, 아래 6개 도메인 테이블은 001~002와 같다.

CREATE TABLE dbo.articles
(
    article_id BIGINT NOT NULL,
    title NVARCHAR(500) NOT NULL,
    sub_title NVARCHAR(500) NULL,
    service_date DATE NOT NULL,
    summary NVARCHAR(MAX) NULL,
    content NVARCHAR(MAX) NULL,
    url NVARCHAR(1000) NULL,
    category_large NVARCHAR(100) NULL,
    category_middle NVARCHAR(100) NULL,
    category_small NVARCHAR(100) NULL,
    entities_extracted_at DATETIME2(7) NULL,
    CONSTRAINT PK_articles PRIMARY KEY CLUSTERED (article_id)
);

CREATE INDEX IX_articles_service_date ON dbo.articles(service_date);

CREATE TABLE dbo.article_entities
(
    entity_id INT IDENTITY(1, 1) NOT NULL,
    article_id BIGINT NOT NULL,
    name NVARCHAR(300) NOT NULL,
    entity_type NVARCHAR(50) NOT NULL,
    CONSTRAINT PK_article_entities PRIMARY KEY CLUSTERED (entity_id),
    CONSTRAINT FK_article_entities_article FOREIGN KEY (article_id)
        REFERENCES dbo.articles(article_id) ON DELETE CASCADE,
    CONSTRAINT UQ_entities_article_entity UNIQUE NONCLUSTERED (article_id, entity_id)
);

CREATE TABLE dbo.article_relations
(
    relation_id INT IDENTITY(1, 1) NOT NULL,
    article_id BIGINT NOT NULL,
    source_entity_id INT NOT NULL,
    target_entity_id INT NOT NULL,
    relation_type NVARCHAR(100) NOT NULL,
    CONSTRAINT PK_article_relations PRIMARY KEY CLUSTERED (relation_id),
    CONSTRAINT FK_article_relations_article FOREIGN KEY (article_id)
        REFERENCES dbo.articles(article_id) ON DELETE CASCADE,
    CONSTRAINT FK_article_relations_source FOREIGN KEY (article_id, source_entity_id)
        REFERENCES dbo.article_entities(article_id, entity_id),
    CONSTRAINT FK_article_relations_target FOREIGN KEY (article_id, target_entity_id)
        REFERENCES dbo.article_entities(article_id, entity_id)
);

CREATE INDEX IX_relations_article ON dbo.article_relations(article_id);

CREATE TABLE dbo.issues
(
    issue_id INT IDENTITY(1, 1) NOT NULL,
    topic NVARCHAR(500) NOT NULL,
    title NVARCHAR(500) NULL,
    summary NVARCHAR(MAX) NULL,
    generated_at DATETIME2(7) NOT NULL,
    CONSTRAINT PK_issues PRIMARY KEY CLUSTERED (issue_id),
    CONSTRAINT UQ_issues_topic UNIQUE NONCLUSTERED (topic)
);

CREATE TABLE dbo.issue_events
(
    event_id INT IDENTITY(1, 1) NOT NULL,
    issue_id INT NOT NULL,
    event_order INT NOT NULL,
    event_date DATE NOT NULL,
    title NVARCHAR(500) NOT NULL,
    summary NVARCHAR(MAX) NULL,
    CONSTRAINT PK_issue_events PRIMARY KEY CLUSTERED (event_id),
    CONSTRAINT FK_issue_events_issue FOREIGN KEY (issue_id)
        REFERENCES dbo.issues(issue_id) ON DELETE CASCADE
);

CREATE INDEX IX_issue_events_issue_order
    ON dbo.issue_events(issue_id, event_order);

CREATE TABLE dbo.issue_event_articles
(
    event_id INT NOT NULL,
    article_id BIGINT NOT NULL,
    relevance_score FLOAT NULL,
    CONSTRAINT PK_issue_event_articles PRIMARY KEY CLUSTERED (event_id, article_id),
    CONSTRAINT FK_iea_event FOREIGN KEY (event_id)
        REFERENCES dbo.issue_events(event_id) ON DELETE CASCADE,
    CONSTRAINT FK_iea_article FOREIGN KEY (article_id)
        REFERENCES dbo.articles(article_id)
);

CREATE INDEX IX_iea_article ON dbo.issue_event_articles(article_id);
