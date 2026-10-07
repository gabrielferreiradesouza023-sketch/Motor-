CREATE TABLE tracking_ids (
    token TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entities(id)
);
CREATE INDEX tracking_ids_entity_idx ON tracking_ids(entity_id);
