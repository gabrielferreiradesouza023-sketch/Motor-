ALTER TABLE actions ADD COLUMN action_kind TEXT GENERATED ALWAYS AS (json_extract(payload,'$.kind')) VIRTUAL;
ALTER TABLE actions ADD COLUMN action_result TEXT GENERATED ALWAYS AS (json_extract(payload,'$.result')) VIRTUAL;
ALTER TABLE actions ADD COLUMN action_entity_id TEXT GENERATED ALWAYS AS (json_extract(payload,'$.payload_json.entity_id')) VIRTUAL;
ALTER TABLE actions ADD COLUMN action_attempt_id TEXT GENERATED ALWAYS AS (json_extract(payload,'$.payload_json.attempt_id')) VIRTUAL;
ALTER TABLE actions ADD COLUMN action_ts TEXT GENERATED ALWAYS AS (json_extract(payload,'$.ts')) VIRTUAL;
CREATE INDEX actions_result_idx ON actions(action_result);
CREATE INDEX actions_attempt_idx ON actions(action_attempt_id,action_result);
CREATE INDEX actions_kind_entity_idx ON actions(action_kind,action_entity_id);
