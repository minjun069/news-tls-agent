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

CREATE INDEX IX_articles_service_date
    ON dbo.articles(service_date);
GO

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
GO

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

CREATE INDEX IX_relations_article
    ON dbo.article_relations(article_id);
GO
