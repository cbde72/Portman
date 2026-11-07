CREATE TABLE app_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    data_revision INTEGER NOT NULL CHECK (data_revision >= 1)
) STRICT;
INSERT INTO app_state(singleton, data_revision) VALUES (1, 1);

CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    kind TEXT NOT NULL CHECK (kind IN ('cash', 'position')),
    subtype TEXT NOT NULL CHECK (subtype IN ('checking', 'savings', 'fixed_term', 'settlement', 'depot', 'crypto')),
    institution TEXT,
    currency TEXT,
    reference_account_id TEXT REFERENCES accounts(account_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    CHECK ((kind = 'cash' AND currency IS NOT NULL AND length(currency) > 0) OR
           (kind = 'position' AND currency IS NULL AND subtype IN ('depot', 'crypto'))),
    CHECK ((kind = 'cash' AND subtype IN ('checking', 'savings', 'fixed_term', 'settlement')) OR
           (kind = 'position' AND subtype IN ('depot', 'crypto')))
) STRICT;

CREATE TABLE account_identifiers (
    identifier_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    identifier_type TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL,
    CHECK (length(trim(identifier_type)) > 0 AND length(trim(value)) > 0),
    UNIQUE(account_id, identifier_type, context, value)
) STRICT;
CREATE INDEX account_identifiers_lookup ON account_identifiers(identifier_type, context, value);

CREATE TABLE instruments (
    instrument_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    asset_type TEXT NOT NULL CHECK (length(trim(asset_type)) > 0),
    revision INTEGER NOT NULL CHECK (revision >= 1)
) STRICT;
CREATE TABLE instrument_identifiers (
    identifier_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    value TEXT NOT NULL,
    CHECK (length(trim(provider)) > 0 AND length(trim(identifier_type)) > 0 AND length(trim(value)) > 0),
    UNIQUE(instrument_id, provider, identifier_type, value)
) STRICT;
CREATE INDEX instrument_identifiers_lookup ON instrument_identifiers(provider, identifier_type, value);

CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (length(trim(kind)) > 0),
    booking_date TEXT NOT NULL CHECK (length(booking_date) = 10),
    trade_date TEXT,
    value_date TEXT,
    original_text TEXT,
    completeness TEXT NOT NULL CHECK (completeness IN ('complete', 'incomplete', 'unknown')),
    correction_of_event_id TEXT REFERENCES events(event_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision >= 1)
) STRICT;
CREATE INDEX events_booking_date ON events(booking_date DESC, event_id DESC);

CREATE TABLE positions (
    position_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    currency TEXT,
    amount_decimal TEXT COLLATE PORTMAN_DECIMAL,
    instrument_id TEXT REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
    quantity_decimal TEXT COLLATE PORTMAN_DECIMAL,
    effective_date TEXT NOT NULL CHECK (length(effective_date) = 10),
    CHECK ((currency IS NOT NULL AND amount_decimal IS NOT NULL AND instrument_id IS NULL AND quantity_decimal IS NULL) OR
           (currency IS NULL AND amount_decimal IS NULL AND instrument_id IS NOT NULL AND quantity_decimal IS NOT NULL)),
    CHECK ((currency IS NOT NULL AND length(currency) > 0) OR currency IS NULL),
    CHECK (amount_decimal IS NULL OR portman_is_decimal(amount_decimal) = 1),
    CHECK (quantity_decimal IS NULL OR portman_is_decimal(quantity_decimal) = 1)
) STRICT;
CREATE INDEX positions_event ON positions(event_id);
CREATE INDEX positions_account_date ON positions(account_id, effective_date);
CREATE INDEX positions_instrument_date ON positions(instrument_id, effective_date) WHERE instrument_id IS NOT NULL;
CREATE INDEX positions_currency_amount ON positions(currency, amount_decimal COLLATE PORTMAN_DECIMAL) WHERE amount_decimal IS NOT NULL;
CREATE INDEX positions_instrument_quantity ON positions(instrument_id, quantity_decimal COLLATE PORTMAN_DECIMAL) WHERE quantity_decimal IS NOT NULL;
CREATE TRIGGER positions_account_kind_insert BEFORE INSERT ON positions
BEGIN
    SELECT CASE
        WHEN (SELECT kind FROM accounts WHERE account_id = NEW.account_id) = 'cash'
             AND NEW.currency IS NULL THEN RAISE(ABORT, 'cash account requires a money position')
        WHEN (SELECT kind FROM accounts WHERE account_id = NEW.account_id) = 'position'
             AND NEW.instrument_id IS NULL THEN RAISE(ABORT, 'position account requires an instrument position')
    END;
END;
CREATE TRIGGER positions_account_kind_update BEFORE UPDATE ON positions
BEGIN
    SELECT CASE
        WHEN (SELECT kind FROM accounts WHERE account_id = NEW.account_id) = 'cash'
             AND NEW.currency IS NULL THEN RAISE(ABORT, 'cash account requires a money position')
        WHEN (SELECT kind FROM accounts WHERE account_id = NEW.account_id) = 'position'
             AND NEW.instrument_id IS NULL THEN RAISE(ABORT, 'position account requires an instrument position')
    END;
END;

CREATE TABLE acquisition_lots (
    lot_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    original_quantity_decimal TEXT NOT NULL CHECK (portman_is_decimal_positive(original_quantity_decimal) = 1),
    acquired_on TEXT CHECK (acquired_on IS NULL OR length(acquired_on) = 10),
    original_cost_decimal TEXT CHECK (original_cost_decimal IS NULL OR portman_is_decimal(original_cost_decimal) = 1),
    cost_currency TEXT,
    CHECK ((original_cost_decimal IS NULL AND cost_currency IS NULL) OR
           (original_cost_decimal IS NOT NULL AND cost_currency IS NOT NULL AND length(cost_currency) > 0))
) STRICT;
CREATE INDEX acquisition_lots_account_instrument ON acquisition_lots(account_id, instrument_id, acquired_on);
CREATE TABLE lot_allocations (
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
    position_id TEXT NOT NULL REFERENCES positions(position_id) ON DELETE RESTRICT,
    lot_id TEXT NOT NULL REFERENCES acquisition_lots(lot_id) ON DELETE RESTRICT,
    source_account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    destination_account_id TEXT REFERENCES accounts(account_id) ON DELETE RESTRICT,
    quantity_decimal TEXT NOT NULL CHECK (portman_is_decimal_positive(quantity_decimal) = 1),
    cost_rational TEXT COLLATE PORTMAN_RATIONAL CHECK (cost_rational IS NULL OR portman_is_rational(cost_rational) = 1),
    PRIMARY KEY(event_id, position_id, lot_id, source_account_id),
    CHECK (destination_account_id IS NULL OR destination_account_id <> source_account_id)
) STRICT;
CREATE INDEX lot_allocations_lot ON lot_allocations(lot_id, event_id);
CREATE TRIGGER lot_allocations_consistent_insert BEFORE INSERT ON lot_allocations
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM positions p JOIN acquisition_lots l ON l.lot_id = NEW.lot_id
        WHERE p.position_id = NEW.position_id AND p.event_id = NEW.event_id
          AND p.instrument_id = l.instrument_id
          AND l.account_id = NEW.source_account_id
          AND p.account_id IN (NEW.source_account_id, COALESCE(NEW.destination_account_id, NEW.source_account_id))
    ) THEN RAISE(ABORT, 'lot allocation must match its event position and instrument') END;
END;
CREATE TRIGGER lot_allocations_consistent_update BEFORE UPDATE ON lot_allocations
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM positions p JOIN acquisition_lots l ON l.lot_id = NEW.lot_id
        WHERE p.position_id = NEW.position_id AND p.event_id = NEW.event_id
          AND p.instrument_id = l.instrument_id
          AND l.account_id = NEW.source_account_id
          AND p.account_id IN (NEW.source_account_id, COALESCE(NEW.destination_account_id, NEW.source_account_id))
    ) THEN RAISE(ABORT, 'lot allocation must match its event position and instrument') END;
END;

CREATE TABLE event_components (
    component_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
    component_type TEXT NOT NULL CHECK (component_type IN ('trade_value', 'fee', 'tax', 'gross', 'withholding', 'interest', 'other')),
    amount_decimal TEXT COLLATE PORTMAN_DECIMAL,
    currency TEXT,
    CHECK (amount_decimal IS NULL OR (portman_is_decimal(amount_decimal) = 1 AND currency IS NOT NULL AND length(currency) > 0))
) STRICT;
CREATE INDEX event_components_event ON event_components(event_id);

CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    original_name TEXT NOT NULL CHECK (length(original_name) > 0),
    relative_path TEXT NOT NULL CHECK (length(relative_path) > 0),
    media_type TEXT,
    imported_at TEXT NOT NULL
) STRICT;
CREATE TABLE event_documents (
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
    page_or_entry TEXT,
    source_role TEXT NOT NULL CHECK (source_role IN ('primary', 'confirmation', 'complement', 'correction', 'other')),
    PRIMARY KEY(event_id, document_id, source_role)
) STRICT;
CREATE INDEX event_documents_document ON event_documents(document_id);

CREATE TABLE imports (
    import_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'preview', 'committed', 'cancelled', 'failed', 'rolled_back')),
    preview_revision INTEGER NOT NULL CHECK (preview_revision >= 1),
    parser_version TEXT,
    schema_version TEXT
) STRICT;
CREATE TABLE import_documents (
    import_id TEXT NOT NULL REFERENCES imports(import_id) ON DELETE RESTRICT,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
    PRIMARY KEY(import_id, document_id)
) STRICT;

CREATE TABLE import_contributions (
    contribution_id TEXT PRIMARY KEY,
    import_id TEXT REFERENCES imports(import_id) ON DELETE RESTRICT,
    event_id TEXT REFERENCES events(event_id) ON DELETE RESTRICT,
    account_id TEXT REFERENCES accounts(account_id) ON DELETE RESTRICT,
    instrument_id TEXT REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
    document_id TEXT REFERENCES documents(document_id) ON DELETE RESTRICT,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('import', 'manual')),
    target_type TEXT NOT NULL CHECK (target_type IN ('event', 'account', 'instrument')),
    field_name TEXT NOT NULL CHECK (length(trim(field_name)) > 0),
    action TEXT NOT NULL CHECK (action IN ('create', 'set', 'link')),
    previous_value_text TEXT,
    value_text TEXT,
    created_at TEXT NOT NULL,
    CHECK ((source_kind = 'import' AND import_id IS NOT NULL) OR (source_kind = 'manual' AND import_id IS NULL)),
    CHECK ((target_type = 'event' AND event_id IS NOT NULL AND account_id IS NULL AND instrument_id IS NULL) OR
           (target_type = 'account' AND event_id IS NULL AND account_id IS NOT NULL AND instrument_id IS NULL) OR
           (target_type = 'instrument' AND event_id IS NULL AND account_id IS NULL AND instrument_id IS NOT NULL))
) STRICT;
CREATE INDEX import_contributions_import ON import_contributions(import_id);
CREATE INDEX import_contributions_target ON import_contributions(target_type, event_id, account_id, instrument_id, field_name);

CREATE TABLE operations (
    request_id TEXT PRIMARY KEY CHECK (length(trim(request_id)) > 0),
    command_type TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (length(input_hash) = 64),
    result_text TEXT NOT NULL,
    completed_at TEXT NOT NULL
) STRICT;

CREATE TABLE balance_index (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    asset_key TEXT NOT NULL,
    currency TEXT,
    instrument_id TEXT REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
    as_of TEXT NOT NULL CHECK (length(as_of) = 10),
    value_decimal TEXT COLLATE PORTMAN_DECIMAL,
    value_rational TEXT COLLATE PORTMAN_RATIONAL,
    completeness TEXT NOT NULL CHECK (completeness IN ('complete', 'incomplete', 'unknown')),
    data_revision INTEGER NOT NULL CHECK (data_revision >= 1),
    PRIMARY KEY(account_id, asset_key, as_of),
    CHECK ((currency IS NOT NULL AND instrument_id IS NULL AND asset_key = 'CURRENCY:' || currency) OR
           (currency IS NULL AND instrument_id IS NOT NULL AND asset_key = 'INSTRUMENT:' || instrument_id)),
    CHECK ((value_decimal IS NULL AND value_rational IS NULL) OR
           (value_decimal IS NOT NULL AND value_rational IS NULL AND portman_is_decimal(value_decimal) = 1) OR
           (value_decimal IS NULL AND value_rational IS NOT NULL AND portman_is_rational(value_rational) = 1))
) STRICT;
CREATE INDEX balance_index_lookup ON balance_index(account_id, asset_key, as_of DESC);

CREATE TABLE fixed_term_details (
    account_id TEXT PRIMARY KEY REFERENCES accounts(account_id) ON DELETE RESTRICT,
    starts_on TEXT NOT NULL CHECK (length(starts_on) = 10),
    matures_on TEXT NOT NULL CHECK (length(matures_on) = 10 AND matures_on >= starts_on),
    agreed_rate_decimal TEXT COLLATE PORTMAN_DECIMAL NOT NULL CHECK (portman_is_decimal(agreed_rate_decimal) = 1)
) STRICT;

CREATE TABLE tax_subjects (
    tax_subject_id TEXT PRIMARY KEY,
    bank_owner_context TEXT NOT NULL,
    owner_label TEXT NOT NULL CHECK (length(trim(owner_label)) > 0)
) STRICT;
CREATE TABLE tax_subject_accounts (
    tax_subject_id TEXT NOT NULL REFERENCES tax_subjects(tax_subject_id) ON DELETE RESTRICT,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    PRIMARY KEY(tax_subject_id, account_id)
) STRICT;
CREATE TABLE exemption_orders (
    order_id TEXT PRIMARY KEY,
    tax_subject_id TEXT NOT NULL REFERENCES tax_subjects(tax_subject_id) ON DELETE RESTRICT,
    tax_year INTEGER NOT NULL CHECK (tax_year >= 1900),
    valid_from TEXT NOT NULL CHECK (length(valid_from) = 10),
    valid_to TEXT CHECK (valid_to IS NULL OR (length(valid_to) = 10 AND valid_to >= valid_from)),
    amount_decimal TEXT COLLATE PORTMAN_DECIMAL NOT NULL CHECK (portman_is_decimal(amount_decimal) = 1 AND substr(amount_decimal, 1, 1) <> '-'),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    UNIQUE(tax_subject_id, tax_year, revision)
) STRICT;
CREATE INDEX exemption_orders_current ON exemption_orders(tax_subject_id, tax_year, revision DESC);
CREATE TABLE tax_consumption_statements (
    statement_id TEXT PRIMARY KEY,
    tax_subject_id TEXT NOT NULL REFERENCES tax_subjects(tax_subject_id) ON DELETE RESTRICT,
    tax_year INTEGER NOT NULL CHECK (tax_year >= 1900),
    meaning TEXT NOT NULL CHECK (meaning IN ('individual', 'cumulative')),
    amount_decimal TEXT COLLATE PORTMAN_DECIMAL,
    as_of TEXT CHECK (as_of IS NULL OR length(as_of) = 10),
    completeness TEXT NOT NULL CHECK (completeness IN ('complete', 'incomplete', 'unknown')),
    CHECK ((amount_decimal IS NULL AND completeness = 'unknown') OR (amount_decimal IS NOT NULL AND portman_is_decimal(amount_decimal) = 1))
) STRICT;
CREATE TABLE tax_consumption_sources (
    statement_id TEXT NOT NULL REFERENCES tax_consumption_statements(statement_id) ON DELETE RESTRICT,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
    import_id TEXT REFERENCES imports(import_id) ON DELETE RESTRICT,
    source_role TEXT NOT NULL CHECK (source_role IN ('primary', 'confirmation', 'correction', 'other')),
    PRIMARY KEY(statement_id, document_id, source_role)
) STRICT;

PRAGMA user_version = 1;
