IF DB_ID(N'{{DATABASE}}') IS NULL
BEGIN
    EXEC(N'CREATE DATABASE [{{DATABASE}}] COLLATE {{COLLATION}}');
END;
GO

USE [{{DATABASE}}];
GO

IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.schema_migrations
    (
        version VARCHAR(3) NOT NULL,
        name VARCHAR(200) NOT NULL,
        checksum CHAR(64) NOT NULL,
        applied_at DATETIME2(7) NOT NULL
            CONSTRAINT DF_schema_migrations_applied_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_schema_migrations PRIMARY KEY CLUSTERED (version)
    );
END;
GO
