"""The approved two-product comparison. Checkpointed; never auto-repeats a task.

Only this process enables new collection. It cannot change the service's private
configuration or publish results. All starts share the existing lifetime ledger.
"""
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research'))
for line in (Path.home()/'.config/outloud/research.env').read_text().splitlines():
    if line.strip() and not line.startswith('#') and '=' in line:
        name,value=line.split('=',1)
        os.environ[name]=value.strip().strip('"').strip("'")

OUT=ROOT/'artifacts/native-comparison-2026-11-08.json'
budget=Path(os.environ.get('OUTLOUD_BUDGET_DB',str(ROOT/'research/.data/provider-budget.sqlite3')))
def reserved():
    with sqlite3.connect('file:'+str(budget)+'?mode=ro',uri=True) as db:
        return db.execute('SELECT COALESCE(SUM(reserved),0) FROM provider_spend').fetchone()[0]

state=json.loads(OUT.read_text()) if OUT.exists() else {
    'approved_extra_microusd':6_000_000,'starting_reservations_microusd':reserved(),
    'products':{},'published':False,
}
cap=min(16_100_000,state['starting_reservations_microusd']+state['approved_extra_microusd'])
os.environ.update(OUTLOUD_EVALUATION_BUDGET_MICROUSD=str(cap),OUTLOUD_PAID_RESEARCH='1',
    OUTLOUD_RETRIEVAL_MODE='native',OUTLOUD_MEDIA_SEARCH_ALLOWED='1',
    OUTLOUD_MEDIA_START_ALLOWED='1',OUTLOUD_TIKTOK_EVALUATION_APPROVED='1',
    OUTLOUD_CONVERSATION_START_ALLOWED='1',OUTLOUD_X_COLLECTOR='raven',
    OUTLOUD_GEMINI_REQUESTS_PER_MINUTE='12')

from app import Project,connect
from product_profile import research_project,research_context
from research_providers import search_brief,native_search_terms,discover_native_media,evaluate
from native_conversations import query_for,discover
from research_routing import media_plan
from research_quality import select_results
from live_discovery import merge_candidates

def save():
    state['reserved_microusd']=reserved()
    state['comparison_reservations_microusd']=state['reserved_microusd']-state['starting_reservations_microusd']
    OUT.write_text(json.dumps(state,indent=2,ensure_ascii=False))

def announce(value):
    print(json.dumps(value,ensure_ascii=False),flush=True)

def error_info(exc):
    # Exception URLs can contain credentials. Persist only type/status.
    response=getattr(exc,'response',None)
    result={'type':type(exc).__name__,'http_status':response.status_code if response is not None else None}
    if response is not None:
        try:
            details=response.json().get('error',{})
            message=str(details.get('message',''))
            for name in ('APIFY_TOKEN','GEMINI_API_KEY'):
                if os.environ.get(name):message=message.replace(os.environ[name],'[redacted]')
            result.update(message=message[:1200],retry_after=response.headers.get('retry-after'))
        except (ValueError,AttributeError):pass
    return result

save()
with connect() as db:
    rows=db.execute('SELECT id,data FROM projects ORDER BY created DESC').fetchall()
    projects={}
    for row in rows:
        raw=json.loads(row['data'])
        if raw.get('name') not in ('Watchers','Cal AI') or raw['name'] in projects:continue
        project=Project(**raw)
        meta=db.execute('SELECT data FROM metadata_cache WHERE url=?',(project.url,)).fetchone() if project.url else None
        projects[project.name]=(row['id'],research_project(project,json.loads(meta['data']) if meta else {}))
if len(projects)!=2:raise SystemExit('Both saved comparison products are required.')

for name in ('Watchers','Cal AI'):
    identifier,project=projects[name]
    record=state['products'].setdefault(name,{'project_id':identifier,'project':project.model_dump(),'collections':{}})
    if '--resume-failures' in sys.argv:
        for key,value in list(record['collections'].items()):
            error=value.get('error',{})
            resumable=error.get('type') in ('OperationalError','MediaPending') or (
                error.get('http_status')==402 and 'concurrent Actor runs' in error.get('message',''))
            if resumable:
                record.setdefault('previous_attempts',[]).append({'collection':key,**value})
                del record['collections'][key]
                record['finished']=False
        if record.get('evaluation_failures'):
            record['finished']=False
            record['evaluation_failures']=[]
    if record.get('finished'):continue
    started=time.monotonic()
    try:
        search_brief(project)
        terms=native_search_terms(project)
        record['context']=research_context(project)
        tasks=media_plan(terms)
        for platform in ('Reddit','X'):
            tasks.append({'platform':platform,'lane':'conversations','query':query_for(project,platform)})
        record['plan']=tasks
        save();announce({'product':name,'stage':'planned','searches':tasks})
    except Exception as exc:
        record['planning_error']=error_info(exc);save();announce({'product':name,'planning_error':record['planning_error']});continue

    def collect(task):
        if task['platform'] in ('TikTok','Instagram'):
            items=discover_native_media(task['phrases'],20,90,task['platform'],task['platform']=='Instagram')
        else:
            items=discover(task['query'],20,90,task['platform'])
        return [{**item,'retrieved_for':task['lane']} for item in items]

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(collect,task):task for task in tasks if task['platform']+':'+task['lane'] not in record['collections']}
        for future in as_completed(jobs):
            task=jobs[future];key=task['platform']+':'+task['lane']
            try:
                sources=future.result()
                record['collections'][key]={'status':'completed','sources':sources,'count':len(sources)}
            except Exception as exc:
                record['collections'][key]={'status':'unavailable','error':error_info(exc),'sources':[],'count':0}
            save();announce({'product':name,'stage':'collected','collection':key,
                **{k:v for k,v in record['collections'][key].items() if k!='sources'}})

    sources=merge_candidates([item for task in record['collections'].values() for item in task['sources']])
    # This comparison isolates native recall: no old indexed corpus, embeddings,
    # URL enrichment or additional provider searches are used to pad the pool.
    record['unique_originals']=len(sources)
    if sources:
        try:
            verdicts={}
            for index in range(0,len(sources),100):
                batch=evaluate(project,sources[index:index+100])
                verdicts.update(batch)
                record.setdefault('evaluation_failures',[]).extend(getattr(batch,'failure_reasons',[]))
            for item in sources:
                if item['id'] in verdicts:item['evaluation']=verdicts[item['id']]
            selected,quality=select_results(project,sources,require_evaluation=True)
            record.update(candidates=sources,selected=selected,quality_report=quality)
        except Exception as exc:
            record['evaluation_error']=error_info(exc)
    record['elapsed_seconds']=round(time.monotonic()-started,1)
    record['finished']=True
    save();announce({'product':name,'stage':'finished','unique_originals':len(sources),
        'selected':{lane:sum(s.get('intent')==lane for s in record.get('selected',[])) for lane in ('discover','competitors','conversations')},
        'evaluation_error':record.get('evaluation_error'),
        'reserved_for_comparison_usd':state['comparison_reservations_microusd']/1_000_000})

save()
announce({'artifact':str(OUT),'reserved_for_comparison_usd':state['comparison_reservations_microusd']/1_000_000,'published':False})
