CREATE TABLE scheduler_runs (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running','complete','failed')),
    payload TEXT NOT NULL CHECK(json_valid(payload))
);
