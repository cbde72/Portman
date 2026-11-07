ALTER TABLE events ADD COLUMN bank_reference TEXT;
ALTER TABLE events ADD COLUMN reference_context TEXT;
CREATE UNIQUE INDEX events_bank_reference_context
    ON events(reference_context, bank_reference)
    WHERE bank_reference IS NOT NULL AND reference_context IS NOT NULL;
PRAGMA user_version = 5;
