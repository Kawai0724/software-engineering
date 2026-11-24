PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
 password_hash TEXT NOT NULL, salt TEXT NOT NULL, nickname TEXT NOT NULL,
 phone TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','admin')),
 fail_count INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 last_active REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS invitations (
 code_hash TEXT PRIMARY KEY, created_by TEXT NOT NULL REFERENCES accounts(id),
 consumed_by TEXT REFERENCES accounts(id)
);
CREATE TABLE IF NOT EXISTS products (
 id TEXT PRIMARY KEY, seller_id TEXT NOT NULL REFERENCES accounts(id),
 title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT '', condition TEXT NOT NULL DEFAULT '',
 price_cents INTEGER, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT,
 violation INTEGER NOT NULL DEFAULT 0, violation_reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS images (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
 filename TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
 admin_id TEXT NOT NULL REFERENCES accounts(id), decision TEXT NOT NULL,
 reason TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
 product_version INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
 buyer_id TEXT NOT NULL REFERENCES accounts(id), seller_id TEXT NOT NULL REFERENCES accounts(id),
 status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 snapshot TEXT NOT NULL, created_at TEXT NOT NULL, confirmed_at TEXT,
 completed_at TEXT, cancelled_at TEXT, cancelled_by TEXT, cancel_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_reservation ON reservations(product_id)
 WHERE status IN ('pending','confirmed');
CREATE TABLE IF NOT EXISTS reports (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
 reporter_id TEXT NOT NULL REFERENCES accounts(id), reason TEXT NOT NULL,
 details TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 handling_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, handled_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_report ON reports(product_id, reporter_id)
 WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS audit_events (
 id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, actor_id TEXT,
 operation TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT,
 request_id TEXT, result TEXT NOT NULL, reason_code TEXT NOT NULL DEFAULT '',
 before_state TEXT, after_state TEXT
);
CREATE TABLE IF NOT EXISTS idempotency (
 actor_id TEXT NOT NULL REFERENCES accounts(id), operation TEXT NOT NULL,
 request_id TEXT NOT NULL, payload_hash TEXT NOT NULL, resource_type TEXT NOT NULL,
 resource_id TEXT NOT NULL, PRIMARY KEY(actor_id, operation, request_id)
);
