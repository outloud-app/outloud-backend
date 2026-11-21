-- Preserve every issued license and held checkout while adding one genuine place.
DROP TRIGGER IF EXISTS founding_license_issued;
DROP TRIGGER IF EXISTS founding_license_refunded;
DROP TRIGGER IF EXISTS founding_license_revoked_on_arrival;
CREATE TABLE founding_slots_next (
 slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 151),claim_hash TEXT UNIQUE,
 session_id TEXT UNIQUE,hold_expires_at INTEGER,issued_at TEXT
);
INSERT INTO founding_slots_next SELECT * FROM founding_slots;
INSERT INTO founding_slots_next(slot) VALUES (151);
DROP TABLE founding_slots;
ALTER TABLE founding_slots_next RENAME TO founding_slots;
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
