ALTER TABLE scheduler_runs RENAME TO scheduler_runs_old;
CREATE TABLE scheduler_runs (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running','complete','failed','skipped')),
    payload TEXT NOT NULL CHECK(json_valid(payload))
);
INSERT INTO scheduler_runs SELECT * FROM scheduler_runs_old;
DROP TABLE scheduler_runs_old;
