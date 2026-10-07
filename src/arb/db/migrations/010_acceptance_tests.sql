CREATE TABLE acceptance_test_entities (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id),
    meta_id TEXT NOT NULL UNIQUE
);
