CREATE TABLE tracker_receipts(source TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), applied INTEGER NOT NULL DEFAULT 0 CHECK(applied IN (0,1)), PRIMARY KEY(source,id));
CREATE TABLE tracker_cursors(source TEXT PRIMARY KEY, event_cursor INTEGER NOT NULL DEFAULT 0 CHECK(event_cursor>=0), sale_cursor INTEGER NOT NULL DEFAULT 0 CHECK(sale_cursor>=0));
