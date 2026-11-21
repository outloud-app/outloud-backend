"""Offline audit of latest saved real research for each distinct product brief."""
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'research'))
from app import Project,connect
from research_retrieval import model_key
from research_readiness import assess
from collect_public import status
from evaluation_worker import status as evaluation_status
seen=set();reports=[]
with connect() as db:rows=db.execute('SELECT data,results FROM projects ORDER BY created DESC').fetchall()
for raw,snapshot in rows:
    project=Project(**json.loads(raw));workspace=json.loads(snapshot)
    if not workspace.get('quality_report'):continue
    key=model_key(project)
    if key in seen:continue
    seen.add(key);reports.append(assess(project,workspace))
report={'projects':reports,'collection':status(),'evaluation_queue':evaluation_status(),'provider_calls':0,'deployed':False}
output=root/'artifacts/product-service-readiness.json'
output.write_text(json.dumps(report,indent=2))
print(json.dumps({'projects_audited':len(reports),'meeting_target_volume':sum(p['target_volume_met'] for p in reports),
                  'collection_checks':len(report['collection']['checks']),'overdue_checks':report['collection']['overdue'],
                  'evaluation_jobs_due':report['evaluation_queue']['due'],
                  'provider_calls':0,'artifact':str(output)}))
