-- Founder-reported Wise purchases are a separate paid cohort, not Stripe events
-- or checkout holds. They do not occupy the 151 online checkout slots.
CREATE TABLE IF NOT EXISTS direct_sales (
 cohort_id TEXT PRIMARY KEY,
 quantity INTEGER NOT NULL CHECK(quantity>0 AND quantity<=49),
 payment_channel TEXT NOT NULL,
 evidence_source TEXT NOT NULL,
 recorded_at TEXT NOT NULL
);
INSERT OR IGNORE INTO direct_sales(cohort_id,quantity,payment_channel,evidence_source,recorded_at)
VALUES ('founding-wise-direct-49',49,'wise','founder_reported','2026-11-01T00:00:00+03:00');
