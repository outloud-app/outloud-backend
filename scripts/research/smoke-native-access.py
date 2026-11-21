"""Small four-platform smoke test after credential rotation; no hidden retries."""
import os,sys,json,shlex,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'research'))
for line in (Path.home()/'.config/outloud/research.env').read_text().splitlines():
 if not line.strip() or line.lstrip().startswith('#'):continue
 k,s,v=line.removeprefix('export ').partition('=')
 if s:
  a=shlex.split(v,comments=True);os.environ[k.strip()]=a[0] if a else ''
os.environ.update(OUTLOUD_PAID_RESEARCH='1',OUTLOUD_RETRIEVAL_MODE='native',OUTLOUD_MEDIA_START_ALLOWED='1',OUTLOUD_MEDIA_SEARCH_ALLOWED='1',OUTLOUD_TIKTOK_EVALUATION_APPROVED='1',OUTLOUD_CONVERSATION_START_ALLOWED='1',OUTLOUD_X_COLLECTOR='raven',OUTLOUD_GEMINI_REQUESTS_PER_MINUTE='12')
from app import Project
from research_providers import discover_native_media,evaluate,MediaPending
from native_conversations import discover
from research_quality import select_results
from native_access import require
require()
remote=Project(name='Remote control sample',description='An iPhone app that controls smart televisions over local Wi-Fi. It replaces a lost physical TV remote with channel, volume and navigation controls.',audience='People who want to control their smart TV from a phone.',keywords=['TV remote','smart TV','lost remote'],platform='iOS',status='launched',category='other')
journal=Project(name='Reflection journal sample',description='A private journaling app for recording daily experiences, reflecting on feelings and finding recurring themes through guided writing prompts.',audience='People who want a regular personal reflection habit.',keywords=['journaling','reflection','writing prompt'],platform='iOS',status='launched',category='other')
tasks=[(remote,'Instagram','TV remote'),(remote,'TikTok','lost TV remote'),(journal,'Reddit','journaling habit'),(journal,'X','journaling habit')]
report={'published':False,'status':'running','platforms':[],'products':[]}
out=ROOT/'artifacts/native-token-smoke-2026-11-20.json'
pools={remote.name:[],journal.name:[]}
for project,platform,query in tasks:
 print(json.dumps({'product':project.name,'platform':platform,'stage':'collecting'}),flush=True)
 try:
  sources=discover_native_media([query],20,90,platform,platform=='Instagram') if platform in ('TikTok','Instagram') else discover(query,20,90,platform)
  pools[project.name].extend(sources)
  record={'product':project.name,'platform':platform,'status':'complete','original_posts':len(sources)}
 except Exception as e:
  r=getattr(e,'response',None)
  record={'product':project.name,'platform':platform,'status':'pending' if isinstance(e,MediaPending) else 'unavailable','error_type':type(e).__name__,'http_status':r.status_code if r is not None else None}
 report['platforms'].append(record);out.write_text(json.dumps(report,indent=2));print(json.dumps(record),flush=True)
 # Stop immediately if credentials/scopes are still unusable. Other networks
 # must not repeat that reservation against the shared testing budget.
 if record.get('http_status') in (401,403):break
for project in (remote,journal):
 sources=pools[project.name]
 if not sources:continue
 print(json.dumps({'product':project.name,'stage':'evaluating','original_posts':len(sources)}),flush=True)
 try:
  verdicts=evaluate(project,sources)
  checked=[{**s,'evaluation':verdicts[s['id']]} for s in sources if s['id'] in verdicts]
  selected,quality=select_results(project,checked,require_evaluation=True)
  report['products'].append({'name':project.name,'original_posts':len(sources),'lane_counts':quality['lane_counts'],'quality_report':quality,'results':selected})
 except Exception as e:report['products'].append({'name':project.name,'original_posts':len(sources),'evaluation_error':type(e).__name__})
 out.write_text(json.dumps(report,indent=2))
report['status']='complete';out.write_text(json.dumps(report,indent=2))
print(json.dumps({'status':'complete','products':[{k:v for k,v in p.items() if k not in ('results','quality_report')} for p in report['products']]}),flush=True)
