-- Separate offer. Never reset, renumber, or rewrite existing licenses.
-- Apply only with the annual Checkout and invoice webhook rollout.
CREATE TABLE IF NOT EXISTS annual_intro_slots (
 slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 10),
 claim_hash TEXT UNIQUE,
 session_id TEXT UNIQUE,
 hold_expires_at INTEGER,
 paid_at TEXT
);
WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM numbers WHERE n<10)
INSERT OR IGNORE INTO annual_intro_slots(slot) SELECT n FROM numbers;
CREATE TABLE IF NOT EXISTS annual_entitlements (
 subscription_id TEXT PRIMARY KEY,
 customer_id TEXT NOT NULL,
 license_session_id TEXT NOT NULL UNIQUE REFERENCES licenses(session_id),
 status TEXT NOT NULL,
 paid_through TEXT,
 last_invoice_id TEXT UNIQUE
);
