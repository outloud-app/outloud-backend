"""Conservative lifetime spend reservations. Failed/uncertain calls keep their reservation."""
import sqlite3
import uuid
from pathlib import Path

class BudgetExceeded(Exception):pass

# Approved 21 November: native validation may reserve up to $100 in total.
# Per-process configuration may impose a lower ceiling, never a higher one.
APPROVED_CEILING_MICROUSD=100_000_000

def reserve(path,provider,maximum_microusd,ceiling_microusd=5_000_000):
    if not isinstance(maximum_microusd,int) or maximum_microusd<=0:raise ValueError('Invalid reservation')
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path,timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS provider_spend(id TEXT PRIMARY KEY,provider TEXT,reserved INTEGER,created TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('BEGIN IMMEDIATE')
        used=db.execute('SELECT COALESCE(SUM(reserved),0) FROM provider_spend').fetchone()[0]
        if used+maximum_microusd>min(ceiling_microusd,APPROVED_CEILING_MICROUSD):raise BudgetExceeded('The approved evaluation budget is reserved or spent. Paid research is paused.')
        identifier=uuid.uuid4().hex
        db.execute('INSERT INTO provider_spend(id,provider,reserved) VALUES(?,?,?)',(identifier,provider,maximum_microusd))
        return identifier
