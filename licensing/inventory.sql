CREATE TABLE IF NOT EXISTS founding_slots (
 slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 151),
 claim_hash TEXT UNIQUE,
 session_id TEXT UNIQUE,
 hold_expires_at INTEGER,
 issued_at TEXT
);
WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM numbers WHERE n<151)
INSERT OR IGNORE INTO founding_slots(slot) SELECT n FROM numbers;
-- Preserve licenses issued before this cap was introduced. A refunded license
-- does not occupy a founding place. This is safe to run again.
WITH existing AS (
 SELECT session_id,created_at,ROW_NUMBER() OVER(ORDER BY created_at,session_id) AS n
 FROM licenses WHERE status!='revoked'
)
UPDATE founding_slots SET
 session_id=(SELECT session_id FROM existing WHERE n=founding_slots.slot),
 issued_at=(SELECT created_at FROM existing WHERE n=founding_slots.slot)
WHERE session_id IS NULL AND claim_hash IS NULL
 AND slot IN (SELECT n FROM existing WHERE n<=151)
 AND (SELECT session_id FROM existing WHERE n=founding_slots.slot) NOT IN (SELECT session_id FROM founding_slots WHERE session_id IS NOT NULL);
CREATE TRIGGER IF NOT EXISTS founding_license_issued AFTER INSERT ON licenses
 WHEN NEW.status!='revoked'
 BEGIN
  UPDATE founding_slots SET issued_at=NEW.created_at,hold_expires_at=NULL WHERE session_id=NEW.session_id;
 END;
CREATE TRIGGER IF NOT EXISTS founding_license_refunded AFTER UPDATE OF status ON licenses
 WHEN NEW.status='revoked' AND OLD.status!='revoked'
 BEGIN
  UPDATE founding_slots SET claim_hash=NULL,session_id=NULL,hold_expires_at=NULL,issued_at=NULL WHERE session_id=NEW.session_id;
 END;
CREATE TRIGGER IF NOT EXISTS founding_license_revoked_on_arrival AFTER INSERT ON licenses
 WHEN NEW.status='revoked'
 BEGIN
  UPDATE founding_slots SET claim_hash=NULL,session_id=NULL,hold_expires_at=NULL,issued_at=NULL WHERE session_id=NEW.session_id;
 END;
