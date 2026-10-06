CREATE TABLE angle_library (id TEXT PRIMARY KEY, angle_id TEXT NOT NULL REFERENCES angles(id), offer_id TEXT NOT NULL REFERENCES offers(id), payload TEXT NOT NULL CHECK(json_valid(payload)));
CREATE UNIQUE INDEX angle_library_geo ON angle_library(angle_id, json_extract(payload, '$.geo'));
CREATE INDEX angle_library_niche ON angle_library(json_extract(payload, '$.niche'));
