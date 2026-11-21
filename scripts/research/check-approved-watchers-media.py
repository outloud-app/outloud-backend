"""One explicitly authorized follow-up check. Resume with --collect; never auto-retry starts."""
import sys,os,json,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research'))
for line in (Path.home()/'.config/outloud/research.env').read_text().splitlines():
    if line.strip() and not line.startswith('#') and '=' in line:
        key,value=line.split('=',1);os.environ[key]=value.strip().strip('"').strip("'")
os.environ['OUTLOUD_MEDIA_START_ALLOWED']='1'
os.environ['OUTLOUD_TIKTOK_EVALUATION_APPROVED']='1'
from app import Project
from live_discovery import call_search,parse_results
from research_providers import start_media_run,collect_media_run,MediaPending,normalize_media,evaluate
from research_quality import select_results
path=ROOT/'artifacts/watchers-followup-media-check.json'
project=Project(name='Watchers',platform='iOS',status='unlaunched',url='',description='Watches the market for traders and alerts them when a symbol matches their selected chart pattern or trend, such as a double bottom. Saves hours of manual chart watching and avoids missing setups while away.',problem='Traders have to keep watching charts and scanning symbols to catch setups. They miss trading opportunities when away from screens and need alerts when a chosen pattern forms.',audience='Traders who manually monitor charts for pattern setups',category='finance')
if '--collect' not in sys.argv and '--evaluate' not in sys.argv:
    if path.exists():raise SystemExit('Check already recorded. Use --collect to resume existing runs.')
    queries=[('Instagram','site:instagram.com/reel "staring at charts"'),('Instagram','site:instagram.com/reel "missing setups"'),('TikTok','site:tiktok.com "staring at charts"'),('TikTok','site:tiktok.com "missing trades" "alerts"')]
    objective='Find original recent social posts about the frustration of watching trading charts constantly, missing setups while away, and using alerts to reclaim time. Preserve original caption and URL. No broad trading lessons, signals or profit claims.'
    def search(pair):
        platform,query=pair
        try:return [s for s in parse_results(call_search(query,objective),project) if s['platform']==platform]
        except Exception:return []
    candidates=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for batch in pool.map(search,queries):candidates.extend(batch)
    unique={s['url']:s for s in candidates}
    state={'project':project.model_dump(),'candidates':list(unique.values()),'runs':[]}
    path.write_text(json.dumps(state,indent=2))
    for platform in ('Instagram','TikTok'):
        batch=[s['url'] for s in state['candidates'] if s['platform']==platform][:10]
        if not batch:continue
        # Persist intent first. A network timeout may have started a run: never retry automatically.
        state['pending_start']=platform;path.write_text(json.dumps(state,indent=2))
        run=start_media_run(platform,batch)
        state['runs'].append(run);state.pop('pending_start',None);path.write_text(json.dumps(state,indent=2))
    print(json.dumps({'candidates':len(unique),'runs':[{'platform':r['platform'],'maximum_charge_usd':r['maximum_charge_usd']} for r in state['runs']]}))
elif '--collect' in sys.argv:
    state=json.loads(path.read_text());project=Project(**state['project'])
    for run in state['runs']:
        if 'rows' not in run:
            try:run['rows']=collect_media_run(run)
            except MediaPending:print(run['platform']+': pending');continue
            path.write_text(json.dumps(state,indent=2))
    print(json.dumps({'runs':[{'platform':r['platform'],'rows':len(r.get('rows',[]))} for r in state['runs']]}))

else:
    import hashlib,sqlite3,httpx
    from research_providers import enrich_media
    state=json.loads(path.read_text());project=Project(**state['project'])
    if not state['runs'] or any('rows' not in run for run in state['runs']):raise SystemExit('Collection must finish first.')
    cache=Path(os.environ.get('OUTLOUD_PROVIDER_CACHE',str(ROOT/'research/.data/provider-media.sqlite3')))
    with sqlite3.connect(cache) as db:
        db.execute('CREATE TABLE IF NOT EXISTS media_jobs(key TEXT PRIMARY KEY,run TEXT,rows TEXT,created REAL)')
        for run in state['runs']:
            urls=sorted(set(s['url'] for s in state['candidates'] if s['platform']==run['platform']))[:10]
            key=hashlib.sha256(json.dumps([run['platform'],urls]).encode()).hexdigest()
            record={k:v for k,v in run.items() if k!='rows'}
            db.execute('INSERT OR REPLACE INTO media_jobs VALUES(?,?,?,?)',(key,json.dumps(record),json.dumps(run['rows']),time.time()))
    os.environ['OUTLOUD_MEDIA_START_ALLOWED']='0'
    enriched,issues=enrich_media(state['candidates'])
    previous=json.loads((ROOT/'artifacts/watchers-final-quality-check.json').read_text()).get('selected',[])
    sources=list({s['url']:s for s in previous+enriched}.values())
    evaluations=evaluate(project,sources)
    for source in sources:
        source.pop('evaluation',None)
        if source['id'] in evaluations:source['evaluation']=evaluations[source['id']]
    selected,report=select_results(project,sources,require_evaluation=True)
    output={'selected':selected,'quality_report':report,'candidates':sources,'collection_issues':issues}
    (ROOT/'artifacts/watchers-followup-quality-check.json').write_text(json.dumps(output,indent=2))
    costs=[]
    with httpx.Client(timeout=15) as client:
        for run in state['runs']:
            result=client.get('https://api.apify.com/v2/actor-runs/'+run['run_id'],headers={'Authorization':'Bearer '+os.environ['APIFY_TOKEN']})
            result.raise_for_status();data=result.json()['data']
            costs.append({'platform':run['platform'],'status':data['status'],'usage_total_usd':data.get('usageTotalUsd'),'approved_maximum_usd':run['maximum_charge_usd'],'rows':len(run['rows'])})
    (ROOT/'artifacts/watchers-followup-costs.json').write_text(json.dumps(costs,indent=2))
    print(json.dumps({'counts':{lane:sum(s['intent']==lane for s in selected) for lane in ('discover','competitors','conversations')},'launch_ready':report['launch_ready'],'costs':costs}))
