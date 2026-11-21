"""Bounded end-to-end native feed validation. Uses approved provider ledger, no web-index search."""
import os,sys,json,shlex,sqlite3,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'research'))
for line in (Path.home()/'.config/outloud/research.env').read_text().splitlines():
 if not line.strip() or line.lstrip().startswith('#'):continue
 k,sep,v=line.removeprefix('export ').partition('=')
 if sep:
  values=shlex.split(v,comments=True);os.environ[k.strip()]=values[0] if values else ''
os.environ.update(OUTLOUD_PAID_RESEARCH='1',OUTLOUD_RETRIEVAL_MODE='native',OUTLOUD_RESEARCH_CACHE_ONLY='0',
 OUTLOUD_MEDIA_START_ALLOWED='1',OUTLOUD_MEDIA_SEARCH_ALLOWED='1',OUTLOUD_TIKTOK_EVALUATION_APPROVED='1',
 OUTLOUD_CONVERSATION_START_ALLOWED='1',OUTLOUD_NATIVE_CONVERSATION_QUERY_LIMIT='1',
 OUTLOUD_X_COLLECTOR='atomus',OUTLOUD_GEMINI_REQUESTS_PER_MINUTE='12')
from app import Project
from live_discovery import research_live
from native_access import require
require()
# Different customer jobs, identical production pipeline. No category-specific queries or verdicts.
cases=[
 dict(name='Remote control sample',description='An iPhone app that controls smart televisions over local Wi-Fi. It replaces a lost physical TV remote with channel, volume and navigation controls.',audience='People who want to control their smart TV from a phone.',keywords=['TV remote','smart TV','lost remote']),
 dict(name='Reflection journal sample',description='A private journaling app for recording daily experiences, reflecting on feelings and finding recurring themes through guided writing prompts.',audience='People who want a regular personal reflection habit.',keywords=['journaling','reflection','writing prompt']),
 dict(name='Nutrition log sample',description='A food diary that helps people record meals and track daily calorie and nutrition intake. It simplifies food logging and reviewing eating habits.',audience='People keeping a daily food and nutrition diary.',keywords=['food diary','calorie','meal prep'])]
out=ROOT/'artifacts/core-feed-validation-2026-11-20.json'
report={'status':'running','published':False,'products':[]}
for fields in cases:
 p=Project(**fields,platform='iOS',status='launched',category='other')
 print(json.dumps({'product':p.name,'stage':'researching'}),flush=True)
 def progress(partial):
  print(json.dumps({'product':p.name,'stage':partial['stage'],'media':len(partial.get('discover',[])),'conversations':len(partial.get('conversations',[]))}),flush=True)
 started=time.time()
 try:
  result=research_live(p,on_progress=progress)
  record={'name':p.name,'seconds':round(time.time()-started),'results':result,'lane_counts':result['quality_report']['lane_counts']}
 except Exception as e:
  record={'name':p.name,'seconds':round(time.time()-started),'error_type':type(e).__name__,'message':str(e)}
 report['products'].append(record);out.write_text(json.dumps(report,indent=2))
 print(json.dumps({k:v for k,v in record.items() if k!='results'}),flush=True)
 # Stop a failing provider/account boundary instead of burning the budget on every product.
 if record.get('error_type') in ('NativeAccessUnavailable','BudgetExceeded'):break
report['status']='complete';out.write_text(json.dumps(report,indent=2))
