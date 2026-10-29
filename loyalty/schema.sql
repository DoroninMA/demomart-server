CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY,
    firebase_uid TEXT UNIQUE,
    email TEXT UNIQUE,
    display_name TEXT NOT NULL,
    card_number TEXT UNIQUE NOT NULL,
    totp_secret TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('customer', 'cashier')),
    fcm_token TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY,
    register_id TEXT NOT NULL,
    receipt_no INTEGER NOT NULL,
    member_id INTEGER REFERENCES members(id),
    amount_cents INTEGER NOT NULL,
    redeem_points INTEGER NOT NULL,
    paid_cents INTEGER NOT NULL,
    earned_points INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('committed', 'refunded')),
    created_at TEXT NOT NULL,
    refunded_at TEXT,
    UNIQUE (register_id, receipt_no)
);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id),
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    kind TEXT NOT NULL CHECK (kind IN ('earn', 'redeem', 'reverse_earn', 'reverse_redeem')),
    points INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identifications (
    ref TEXT PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ledger_member_idx ON ledger(member_id);
CREATE INDEX IF NOT EXISTS sales_member_idx ON sales(member_id);
