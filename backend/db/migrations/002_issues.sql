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
GO

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
GO

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

CREATE INDEX IX_iea_article
    ON dbo.issue_event_articles(article_id);
GO
