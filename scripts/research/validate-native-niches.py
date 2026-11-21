"""Bounded live acceptance sample across independent product categories.
Uses the existing user-authorized ledger; never raises its ceiling.
"""
import os,sys,json,shlex,time,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research'))
for line in (Path.home()/'.config/outloud/research.env').read_text().splitlines():
 if not line.strip() or line.lstrip().startswith('#'):continue
 key,sep,value=line.removeprefix('export ').partition('=')
 if sep:
  parts=shlex.split(value,comments=True);os.environ[key.strip()]=parts[0] if parts else ''
os.environ.update(OUTLOUD_PAID_RESEARCH='1',OUTLOUD_RETRIEVAL_MODE='native',OUTLOUD_RESEARCH_CACHE_ONLY='0',
 OUTLOUD_MEDIA_START_ALLOWED='1',OUTLOUD_MEDIA_SEARCH_ALLOWED='1',OUTLOUD_TIKTOK_EVALUATION_APPROVED='1',
 OUTLOUD_CONVERSATION_START_ALLOWED='1',OUTLOUD_NATIVE_CONVERSATION_QUERY_LIMIT='1',OUTLOUD_X_COLLECTOR='raven',
 OUTLOUD_GEMINI_REQUESTS_PER_MINUTE='12')
from app import Project
from live_discovery import research_live
from research_retrieval import connect
cases=[
 dict(name='Remote control sample',description='An iPhone app that controls smart televisions over local Wi-Fi. It replaces a lost physical TV remote with channel, volume and navigation controls.', audience='People who want to control their smart TV from a phone.', keywords=['TV remote','smart TV','lost remote']),
 dict(name='Reflection journal sample',description='A private journaling app for recording daily experiences, reflecting on feelings and finding recurring themes through guided writing prompts.', audience='People who want a regular personal reflection habit.', keywords=['journaling','reflection','writing prompt']),
 dict(name='Nutrition log sample',description='A food diary that helps people record meals and track daily calorie and nutrition intake. It simplifies food logging and reviewing eating habits.', audience='People keeping a daily food and nutrition diary.', keywords=['food diary','calorie','meal prep']),
]
report={'products':[],'provider_calls_scope':'Native platform collection, product planning, embeddings and evidence evaluation. No web-index search.',
 'conversation_groups_per_platform':1,'published':False}
out=ROOT/'artifacts/native-niches-2026-11-20.json';out.parent.mkdir(exist_ok=True)
for brief in cases:
 p=Project(**brief,platform='iOS',status='launched',category='other')
 started=time.monotonic()
 print(json.dumps({'product':p.name,'stage':'starting'}),flush=True)
 try:
  def progress(snapshot):
   print(json.dumps({'product':p.name,'stage':snapshot.get('stage'),'checked_results':len(snapshot.get('discover',[]))+len(snapshot.get('conversations',[]))}),flush=True)
  result=research_live(p,on_progress=progress)
  entry={'name':p.name,'status':'complete','elapsed_seconds':round(time.monotonic()-started,1),
   'lane_counts':result['quality_report']['lane_counts'],'coverage':result['coverage'],
   'issues':result['research_issues'],'quality_report':result['quality_report'],
   'results':{'discover':result['discover'],'conversations':result['conversations']}}
 except Exception as e:
  entry={'name':p.name,'status':'unavailable','error_type':type(e).__name__,'elapsed_seconds':round(time.monotonic()-started,1)}
  if isinstance(e,sqlite3.DatabaseError):entry['diagnostic']=str(e)
 report['products'].append(entry)
 out.write_text(json.dumps(report,indent=2))
 print(json.dumps({k:v for k,v in entry.items() if k not in ('results','quality_report')}),flush=True)
 # No hidden retries. Preserve diagnostic/cached evidence before moving on.
