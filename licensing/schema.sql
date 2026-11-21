CREATE TABLE IF NOT EXISTS checkout_claims (claim_hash TEXT PRIMARY KEY,session_id TEXT NOT NULL UNIQUE,expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS licenses (session_id TEXT PRIMARY KEY,key_hash TEXT NOT NULL UNIQUE,email TEXT NOT NULL,payment_intent TEXT, status TEXT NOT NULL CHECK(status IN ('reserved','active','revoked')),created_at TEXT NOT NULL,livemode INTEGER NOT NULL,access_starts_at TEXT,access_ends_at TEXT);
CREATE INDEX IF NOT EXISTS licenses_payment ON licenses(payment_intent);
CREATE TABLE IF NOT EXISTS activations (session_id TEXT NOT NULL REFERENCES licenses(session_id),device_hash TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,PRIMARY KEY(session_id,device_hash));
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY,type TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payment_risks (payment_intent TEXT PRIMARY KEY,event_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits(bucket TEXT PRIMARY KEY,attempts INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS direct_sales (cohort_id TEXT PRIMARY KEY,quantity INTEGER NOT NULL CHECK(quantity>0 AND quantity<=49),payment_channel TEXT NOT NULL,evidence_source TEXT NOT NULL,recorded_at TEXT NOT NULL);
