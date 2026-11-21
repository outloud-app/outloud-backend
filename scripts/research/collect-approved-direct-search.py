"""Resume the already-authorized direct search; this script never starts a run."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research'))
for line in (Path.home()/'.config/outloud/research.env').read_text().splitlines():
 if line.strip() and not line.startswith('#') and '=' in line:
  key,value=line.split('=',1);os.environ[key]=value.strip().strip('"').strip("'")
os.environ.update(OUTLOUD_MEDIA_START_ALLOWED='0',OUTLOUD_MEDIA_SEARCH_ALLOWED='0')
from research_providers import collect_media_run,MediaPending,sources_from_media_rows,evaluate
from research_quality import select_results
from app import Project
import httpx
path=ROOT/'artifacts/watchers-direct-search-check.json';state=json.loads(path.read_text())
run=state['run']
if 'rows' not in state:
 try:state['rows']=collect_media_run(run)
 except MediaPending:raise SystemExit('Existing direct search is still running; no new run started.')
 with httpx.Client(timeout=15) as client:
  response=client.get('https://api.apify.com/v2/actor-runs/'+run['run_id'],headers={'Authorization':'Bearer '+os.environ['APIFY_TOKEN']})
  response.raise_for_status();info=response.json()['data']
 state['cost']={'status':info['status'],'usage_total_usd':info.get('usageTotalUsd'),'approved_maximum_usd':.50}
 path.write_text(json.dumps(state,indent=2))
if 'quality_report' not in state:
 project=Project(**json.loads((ROOT/'artifacts/watchers-followup-media-check.json').read_text())['project'])
 sources=sources_from_media_rows(state['rows'],'TikTok')
 evaluations=evaluate(project,sources) if sources else {}
 for source in sources:
  if source['id'] in evaluations:source['evaluation']=evaluations[source['id']]
 selected,report=select_results(project,sources,require_evaluation=True)
 state.update(candidates=sources,selected=selected,quality_report=report)
 path.write_text(json.dumps(state,indent=2))
print(json.dumps({'rows':len(state['rows']),'selected':len(state['selected']),'for_you':sum(s['intent']=='discover' for s in state['selected']),'cost':state['cost']}))
from research_providers import remember_public_sources
remember_public_sources(state['candidates'])
