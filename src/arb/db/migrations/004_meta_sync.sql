CREATE TABLE meta_daily(source TEXT NOT NULL, ad_id TEXT NOT NULL, period TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), PRIMARY KEY(source,ad_id,period));
CREATE TABLE meta_sync_runs(id TEXT PRIMARY KEY, ts TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('complete','failed')), error_kind TEXT);
CREATE TABLE metric_adjustments(id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id), payload TEXT NOT NULL CHECK(json_valid(payload)));
CREATE TRIGGER adjustments_no_update BEFORE UPDATE ON metric_adjustments BEGIN SELECT RAISE(ABORT, 'adjustments are append-only'); END;
CREATE TRIGGER adjustments_no_delete BEFORE DELETE ON metric_adjustments BEGIN SELECT RAISE(ABORT, 'adjustments are append-only'); END;
