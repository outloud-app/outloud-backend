"""Opt-in bounded collection with durable per-product/network schedules.
Collection stores candidates only: successful collection is NOT qualified research.
--status and --dry-run make no provider calls. --watch must be started explicitly.
"""
import argparse
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from research_retrieval import connect, cached_model, model_key
from research_providers import remember_public_sources
from live_discovery import call_search, parse_results, fresh_query

CADENCE={'conversations':86400,'for_you':259200,'competitors':259200}
NETWORKS={'conversations':('Reddit','X'),'for_you':('Instagram','TikTok'),
          'competitors':('Instagram','TikTok','Reddit','X')}
LEASE_SECONDS=120


def stored_project(raw):
    """Internal publisher context is longer than the public 1200-character brief."""
    from app import Project
    data=json.loads(raw)
    description=data.get('description')
    if not isinstance(description,str) or len(description)>10000:
        raise ValueError('Invalid stored research context.')
    project=Project(**{**data,'description':description[:1200]})
    return project.model_copy(update={'description':description})


def setup(db):
    db.execute('CREATE TABLE IF NOT EXISTS collection_subscriptions(key TEXT PRIMARY KEY,project TEXT,cursor INTEGER DEFAULT 0,updated REAL DEFAULT 0)')
    db.execute("""CREATE TABLE IF NOT EXISTS collection_checks(
      key TEXT,lane TEXT,platform TEXT,cursor INTEGER NOT NULL DEFAULT 0,
      next_due REAL NOT NULL DEFAULT 0,last_attempt REAL,last_success REAL,
      failures INTEGER NOT NULL DEFAULT 0,error_type TEXT,collected INTEGER NOT NULL DEFAULT 0,
      lease TEXT,lease_until REAL NOT NULL DEFAULT 0,PRIMARY KEY(key,lane,platform))""")


def subscribe(project):
    with connect() as db:
        setup(db)
        key=model_key(project)
        db.execute('INSERT OR IGNORE INTO collection_subscriptions(key,project) VALUES(?,?)',(key,json.dumps(project.model_dump())))
        for lane,platforms in NETWORKS.items():
            for platform in platforms:
                db.execute('INSERT OR IGNORE INTO collection_checks(key,lane,platform) VALUES(?,?,?)',(key,lane,platform))


def migrate_subscriptions():
    with connect() as db:
        setup(db)
        rows=db.execute('SELECT project FROM collection_subscriptions').fetchall()
    for raw, in rows:subscribe(stored_project(raw))


def plan_queries(project,model,lane,platform,include_feeds=True):
    domains={'Reddit':'reddit.com','X':'x.com','Instagram':'instagram.com','TikTok':'tiktok.com'}
    phrases=model.get(lane,[])
    queries=[]
    if lane=='conversations' and platform=='Reddit' and include_feeds:
        queries.extend('community-feed:'+s for s in model.get('subreddits',[])[:30])
    for index,phrase in enumerate(phrases):
        if not isinstance(phrase,str) or not phrase.strip():continue
        known=project.competitors
        competitor=known[index]+' ' if lane=='competitors' and index<len(known) else ''
        queries.append('site:'+domains[platform]+' '+competitor+phrase)
    # Explore the wider niche for creative inspiration, without broadening the
    # customer-need and competitor contracts. These remain unverified candidates.
    if lane=='for_you':
        for topic in model.get('adjacent_topics',[])[:8]:
            if isinstance(topic,str) and topic.strip():
                queries.append('site:'+domains[platform]+' '+topic.strip()[:100])
    return list(dict.fromkeys(queries))


def status(now=None):
    now=time.time() if now is None else now
    migrate_subscriptions()
    with connect() as db:
        rows=db.execute('SELECT key,lane,platform,next_due,last_attempt,last_success,failures,error_type,collected,lease_until FROM collection_checks ORDER BY key,lane,platform').fetchall()
    checks=[]
    for key,lane,platform,due,attempt,success,failures,error,count,lease_until in rows:
        state='running' if lease_until>now else 'retry_wait' if failures and due>now else 'due' if due<=now else 'scheduled'
        checks.append(dict(product_key=key,lane=lane,platform=platform,state=state,next_due=due,
          last_attempt=attempt,last_success=success,error_type=error,consecutive_failures=failures,
          last_collected=count,overdue=success is None or now-success>CADENCE[lane]))
    return {'checks':checks,'due':sum(c['state']=='due' for c in checks),
            'overdue':sum(c['overdue'] for c in checks),'note':'Collection health only; counts are candidates, not accepted matches.'}


def claim(max_queries,now,include_feeds,native=False):
    migrate_subscriptions()
    tasks=[]
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute("""SELECT c.key,s.project,c.lane,c.platform,c.cursor,c.failures
          FROM collection_checks c JOIN collection_subscriptions s ON c.key=s.key
          WHERE c.next_due<=? AND c.lease_until<=?
          ORDER BY c.next_due,COALESCE(c.last_attempt,0),c.key,c.lane,c.platform""",(now,now)).fetchall()
        for key,raw,lane,platform,cursor,failures in rows:
            project=stored_project(raw);model=cached_model(project)
            if not model:continue
            if native:
                from native_collection import queries as native_queries
                queries=native_queries(project,model,lane,platform)
            else:queries=plan_queries(project,model,lane,platform,include_feeds)
            if not queries:continue
            query=queries[cursor%len(queries)]
            if not native and not query.startswith('community-feed:'):query=fresh_query(platform,query,lane=lane)
            lease=uuid.uuid4().hex
            db.execute('UPDATE collection_checks SET lease=?,lease_until=?,last_attempt=? WHERE key=? AND lane=? AND platform=?',(lease,now+LEASE_SECONDS,now,key,lane,platform))
            tasks.append(dict(key=key,project=project,lane=lane,platform=platform,query=query,query_count=len(queries),lease=lease,failures=failures))
            if len(tasks)>=max_queries:break
    return tasks


def collect_once(max_queries=4,search=call_search,now=None):
    if isinstance(max_queries,bool) or not isinstance(max_queries,int) or not 1<=max_queries<=4:
        raise ValueError('A collection tick allows one to four queries.')
    from app import connect as app_connect,consume,SEARCH_DAILY_LIMIT
    fixed_clock=now is not None
    now=time.time() if now is None else now
    native=search is call_search
    tasks=claim(max_queries,now,False,native=native)
    def fetch(task):
        try:
            # Consume immediately before the attempt. A rejected quota does not
            # become a successful zero-result check or roll back other attempts.
            with app_connect() as db:
                db.execute('BEGIN IMMEDIATE')
                consume(db,'public-search:'+time.strftime('%Y-%m-%d',time.gmtime(now)),SEARCH_DAILY_LIMIT)
            query=task['query'];project=task['project']
            if native:
                from native_collection import collect
                rows=collect(task)
            elif query.startswith('community-feed:'):
                from community_feeds import fetch_recent
                rows=fetch_recent(query.split(':',1)[1])
            else:
                objective=('Find original public posts for this customer problem: '+(project.problem or project.description)+'. '
                  +('Find unresolved audience questions and frustrations from the last 30 days. Exclude product promotion and resolved stories.' if task['lane']=='conversations' else
                    'Find posts from actual competing products solving the same customer job.' if task['lane']=='competitors' else
                    'Find inspiring, entertaining or useful creative posts for this audience; exclude competing product pitches.')
                  +' Preserve original publication dates, text and links. Never invent counts or media.')
                rows=[s for s in parse_results(search(query,objective),project) if s['platform']==task['platform']]
            remember_public_sources(rows)
            return task,len(rows),None
        except Exception as error:
            # Store only the exception class, never provider tokens or raw bodies.
            return task,0,type(error).__name__
    with ThreadPoolExecutor(max_workers=2) as pool:output=list(pool.map(fetch,tasks))
    with connect() as db:
        for task,count,error in output:
            finished=now if fixed_clock else time.time()
            failures=task['failures']+1 if error else 0
            # Rotate through the whole query plan within the refresh window.
            # Previously eighteen phrases meant eighteen DAYS for Conversations
            # (and six creative phrases took eighteen days). Each tick and the
            # shared daily allowance still enforce the same acquisition bounds.
            delay=min(86400,3600*2**min(failures-1,5)) if error else max(1800,CADENCE[task['lane']]/task['query_count'])
            db.execute("""UPDATE collection_checks SET next_due=?,failures=?,error_type=?,collected=?,
              last_success=CASE WHEN ? IS NULL THEN ? ELSE last_success END,
              cursor=cursor+CASE WHEN ? IS NULL THEN 1 ELSE 0 END,lease=NULL,lease_until=0
              WHERE key=? AND lane=? AND platform=? AND lease=?""",
              (finished+delay,failures,error,count,error,finished,error,task['key'],task['lane'],task['platform'],task['lease']))
    return {'queries':len(tasks),'collected':sum(count for _,count,_ in output),
            'succeeded':sum(error is None for _,_,error in output),'failed':sum(error is not None for _,_,error in output)}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for flag in ('watch','once','status','dry-run','refresh-cached','queue-evaluations','evaluate-once'):parser.add_argument('--'+flag,action='store_true')
    args=parser.parse_args()
    if args.status or args.dry_run:
        from evaluation_worker import status as evaluation_status
        print(json.dumps({**status(),'evaluation_queue':evaluation_status()}),flush=True)
    elif args.queue_evaluations:
        from evaluation_worker import enqueue_subscriptions
        print(json.dumps(enqueue_subscriptions()),flush=True)
    elif args.evaluate_once:
        from evaluation_worker import run_once
        from workspace_refresh import publish_saved
        result=run_once()
        result['workspace_refresh']=publish_saved()
        print(json.dumps(result),flush=True)
    elif args.refresh_cached:
        from workspace_refresh import publish_saved
        print(json.dumps(publish_saved()),flush=True)
    else:
        while True:
            try:
                result=collect_once()
                from evaluation_worker import enqueue_subscriptions
                result['evaluation_queue']=enqueue_subscriptions()
                from workspace_refresh import publish_saved
                result['workspace_refresh']=publish_saved()
                print(json.dumps(result),flush=True)
            except Exception as error:print(json.dumps({'status':'paused','reason':type(error).__name__}),flush=True)
            if not args.watch:break
            time.sleep(1800)
