CREATE TABLE instrument_identifiers_contextual (
    identifier_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    context TEXT NOT NULL CHECK (length(trim(context)) > 0),
    value TEXT NOT NULL,
    CHECK (length(trim(provider)) > 0 AND length(trim(identifier_type)) > 0 AND length(trim(value)) > 0),
    UNIQUE(instrument_id, provider, identifier_type, context, value)
) STRICT;
INSERT INTO instrument_identifiers_contextual(identifier_id, instrument_id, provider, identifier_type, context, value)
SELECT identifier_id, instrument_id, provider, identifier_type,
       CASE WHEN provider = 'instrument' THEN 'standard' ELSE 'unspecified' END,
       value
FROM instrument_identifiers;
DROP TABLE instrument_identifiers;
ALTER TABLE instrument_identifiers_contextual RENAME TO instrument_identifiers;
CREATE INDEX instrument_identifiers_lookup ON instrument_identifiers(provider, context, identifier_type, value);

ALTER TABLE opening_entries ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'manual' CHECK (source_kind = 'manual');
ALTER TABLE opening_entries ADD COLUMN history_scope TEXT NOT NULL DEFAULT 'starting_balance' CHECK (history_scope = 'starting_balance');

CREATE TRIGGER referenced_account_must_remain_cash
BEFORE UPDATE OF kind ON accounts
WHEN NEW.kind <> 'cash' AND EXISTS (SELECT 1 FROM accounts WHERE reference_account_id = OLD.account_id)
BEGIN
    SELECT RAISE(ABORT, 'a referenced account must remain a cash account');
END;

PRAGMA user_version = 3;
