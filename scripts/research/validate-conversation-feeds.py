"""Exercise the production conversation planner and both current native adapters."""
import os,sys,json,shlex
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'research'))
for line in (Path.home()/'.config/outloud/research.env').read_text().splitlines():
 k,s,v=line.removeprefix('export ').partition('=')
 if s:
  parts=shlex.split(v,comments=True);os.environ[k.strip()]=parts[0] if parts else ''
os.environ.update(OUTLOUD_PAID_RESEARCH='1',OUTLOUD_CONVERSATION_START_ALLOWED='1',OUTLOUD_GEMINI_REQUESTS_PER_MINUTE='12')
from app import Project
from native_conversations import discover,queries_for
from research_providers import evaluate,remembered_candidates,cached_evaluations
from research_quality import select_results
base=json.loads((ROOT/'artifacts/core-feed-validation-2026-11-20.json').read_text())
# Read the same documented briefs as the end-to-end run, with no bespoke query.
import ast
source=(ROOT/'scripts/research/validate-core-feeds.py').read_text()
parsed=ast.parse(source)
assignment=next(n for n in parsed.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='cases' for t in n.targets))
# Only evaluate the literal dict constructors from our own fixed test file.
cases=eval(compile(ast.Expression(assignment.value),'<validation-briefs>','eval'),{'dict':dict,'__builtins__':{}})
report={'published':False,'status':'running','products':[]}
out=ROOT/'artifacts/core-conversation-validation-2026-11-20.json'
for fields in cases:
 p=Project(**fields,platform='iOS',status='launched',category='other')
 tasks=[]
 for platform in ('X','Reddit'):
  try:tasks.append((platform,queries_for(p,platform)[1]))
  except Exception as e:print(json.dumps({'name':p.name,'platform':platform,'error':type(e).__name__}),flush=True)
 posts=[];collection=[]
 with ThreadPoolExecutor(max_workers=2) as pool:
  futures=[(platform,q,pool.submit(discover,q,20,90,platform)) for platform,q in tasks]
  for platform,q,f in futures:
   try:
    rows=f.result();posts.extend(rows);collection.append({'platform':platform,'query':q,'original_posts':len(rows)})
   except Exception as e:collection.append({'platform':platform,'error':type(e).__name__})
 print(json.dumps({'name':p.name,'collections':collection}),flush=True)
 # Include current original sample posts already collected by the connectivity probe.
 if p.name=='Reflection journal sample':
  probe=json.loads((ROOT/'artifacts/conversation-query-probe-2026-11-20.json').read_text())
  posts.extend(row for result in probe.values() for row in result.get('posts',[]))
 posts=list({s['id']:s for s in posts}.values())[:80]
 try:
  decisions=evaluate(p,posts)
  checked=cached_evaluations(p,remembered_candidates(p,cached_only=True))
  selected,quality=select_results(p,checked,require_evaluation=True)
  row={'name':p.name,'lane_counts':quality['lane_counts'],'collections':collection,'results':selected,'quality_report':quality}
 except Exception as e:row={'name':p.name,'collections':collection,'error_type':type(e).__name__,'message':str(e)}
 report['products'].append(row);out.write_text(json.dumps(report,indent=2))
 print(json.dumps({k:v for k,v in row.items() if k not in ('results','quality_report')}),flush=True)
report['status']='complete';out.write_text(json.dumps(report,indent=2))
