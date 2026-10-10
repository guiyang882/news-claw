PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

-- Keep task-topic links in tasks.config_json.topic_ids instead of a join table.
UPDATE tasks
SET config_json = json_set(
    config_json,
    '$.topic_ids',
    json((SELECT json_group_array(task_topics.topic_id)
          FROM task_topics
          WHERE task_topics.task_id = tasks.id))
)
WHERE EXISTS (SELECT 1 FROM task_topics WHERE task_topics.task_id = tasks.id);

-- Fold source metadata and document-topic assignments into each document row.
CREATE TABLE documents_compact (
    id TEXT PRIMARY KEY,
    source_json TEXT NOT NULL DEFAULT '{}',
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content_type TEXT,
    http_status INTEGER,
    raw_path TEXT NOT NULL,
    metadata_path TEXT,
    normalized_path TEXT,
    language TEXT,
    topic_links_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE (canonical_url, content_hash)
);

INSERT INTO documents_compact (
    id, source_json, canonical_url, title, published_at, fetched_at, content_hash,
    content_type, http_status, raw_path, metadata_path, normalized_path, language,
    topic_links_json, created_at
)
SELECT
    d.id,
    CASE WHEN s.id IS NULL THEN '{}'
         ELSE json_object(
             'id', s.id,
             'name', s.name,
             'source_type', s.source_type,
             'canonical_url', s.canonical_url,
             'config_json', json(s.config_json),
             'created_at', s.created_at,
             'updated_at', s.updated_at
         )
    END,
    d.canonical_url, d.title, d.published_at, d.fetched_at, d.content_hash,
    d.content_type, d.http_status, d.raw_path, d.metadata_path, d.normalized_path,
    d.language,
    COALESCE((
        SELECT json_group_array(json_object(
            'topic_id', dt.topic_id,
            'assigned_by', dt.assigned_by,
            'confidence', dt.confidence,
            'created_at', dt.created_at
        ))
        FROM document_topics AS dt
        WHERE dt.document_id = d.id
    ), '[]'),
    d.created_at
FROM documents AS d
LEFT JOIN sources AS s ON s.id = d.source_id;

DROP TABLE document_topics;
DROP TABLE task_topics;
DROP TABLE documents;
ALTER TABLE documents_compact RENAME TO documents;
DROP TABLE sources;

CREATE INDEX idx_documents_published ON documents(published_at);
CREATE INDEX idx_documents_hash ON documents(content_hash);

COMMIT;
PRAGMA foreign_keys = ON;
