CREATE TABLE smoke_campaigns (
    campaign_id TEXT PRIMARY KEY REFERENCES entities(id),
    cap_cents INTEGER NOT NULL CHECK(cap_cents > 0)
);
CREATE TABLE smoke_entities (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id),
    campaign_id TEXT NOT NULL REFERENCES smoke_campaigns(campaign_id)
);
