CREATE TABLE opening_entries (
    opening_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE REFERENCES events(event_id) ON DELETE RESTRICT,
    position_id TEXT NOT NULL UNIQUE REFERENCES positions(position_id) ON DELETE RESTRICT,
    opening_kind TEXT NOT NULL CHECK (opening_kind IN ('money', 'quantity')),
    effective_date TEXT NOT NULL CHECK (length(effective_date) = 10),
    cost_basis_status TEXT NOT NULL CHECK (cost_basis_status IN ('not_applicable', 'known', 'unknown')),
    lot_id TEXT REFERENCES acquisition_lots(lot_id) ON DELETE RESTRICT,
    note TEXT,
    CHECK ((opening_kind = 'money' AND cost_basis_status = 'not_applicable' AND lot_id IS NULL) OR
           (opening_kind = 'quantity' AND cost_basis_status IN ('known', 'unknown') AND lot_id IS NOT NULL))
) STRICT;
CREATE INDEX opening_entries_date ON opening_entries(effective_date, opening_id);
CREATE TRIGGER opening_entry_consistency_insert BEFORE INSERT ON opening_entries
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM events e JOIN positions p ON p.event_id = e.event_id
        WHERE e.event_id = NEW.event_id AND e.kind = 'opening_balance'
          AND p.position_id = NEW.position_id AND p.effective_date = NEW.effective_date
          AND ((NEW.opening_kind = 'money' AND p.currency IS NOT NULL AND p.amount_decimal IS NOT NULL AND p.instrument_id IS NULL)
            OR (NEW.opening_kind = 'quantity' AND p.currency IS NULL AND p.instrument_id IS NOT NULL AND p.quantity_decimal IS NOT NULL))
    ) THEN RAISE(ABORT, 'opening entry must reference its matching opening event position') END;
    SELECT CASE WHEN NEW.opening_kind = 'quantity' AND NOT EXISTS (
        SELECT 1 FROM acquisition_lots l JOIN positions p ON p.position_id = NEW.position_id
        WHERE l.lot_id = NEW.lot_id AND l.instrument_id = p.instrument_id AND l.account_id = p.account_id
    ) THEN RAISE(ABORT, 'opening lot must match position account and instrument') END;
    SELECT CASE WHEN NEW.opening_kind = 'quantity' AND NEW.cost_basis_status = 'known' AND
        (SELECT original_cost_decimal FROM acquisition_lots WHERE lot_id = NEW.lot_id) IS NULL
        THEN RAISE(ABORT, 'known cost basis requires a known lot cost') END;
    SELECT CASE WHEN NEW.opening_kind = 'quantity' AND NEW.cost_basis_status = 'unknown' AND
        (SELECT original_cost_decimal FROM acquisition_lots WHERE lot_id = NEW.lot_id) IS NOT NULL
        THEN RAISE(ABORT, 'unknown cost basis must not contain an imputed lot cost') END;
END;
CREATE TRIGGER account_reference_must_be_cash_insert BEFORE INSERT ON accounts
WHEN NEW.reference_account_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT kind FROM accounts WHERE account_id = NEW.reference_account_id) <> 'cash'
        THEN RAISE(ABORT, 'reference account must be a cash account') END;
END;
CREATE TRIGGER account_reference_must_be_cash_update BEFORE UPDATE OF reference_account_id ON accounts
WHEN NEW.reference_account_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT kind FROM accounts WHERE account_id = NEW.reference_account_id) <> 'cash'
        THEN RAISE(ABORT, 'reference account must be a cash account') END;
END;

PRAGMA user_version = 2;
