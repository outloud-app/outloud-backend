"""Durable candidate inbox. Queueing is local; evaluation is explicitly opt-in.

The provider's reservation ledger still authorizes every request. No watch loop
enables paid evaluation implicitly, and unavailable decisions never publish.
"""
import json
import os
import time
import uuid
from research_retrieval import connect,model_key
from research_providers import cached_evaluations,evaluation_key,evaluate
from collect_public import stored_project

LEASE_SECONDS=300


def setup(db):
    db.execute('''CREATE TABLE IF NOT EXISTS evaluation_jobs(
      key TEXT PRIMARY KEY,product_key TEXT NOT NULL,url TEXT NOT NULL,
      project TEXT NOT NULL,source TEXT NOT NULL,state TEXT NOT NULL,
      created REAL NOT NULL,next_due REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
      error_type TEXT,lease TEXT,lease_until REAL NOT NULL DEFAULT 0,completed REAL)''')
    db.execute('CREATE INDEX IF NOT EXISTS evaluation_due ON evaluation_jobs(state,next_due)')


def bounded(value,maximum,label):
    if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=maximum:
        raise ValueError(label)


def enqueue(project,sources,limit=90,now=None):
    """Canonical originals only. Drop supplied verdicts, then check exact cache keys."""
    from live_discovery import post_identity,publication,merge_candidates,balanced_candidates
    bounded(limit,100,'Queue one to one hundred candidates per product.')
    now=time.time() if now is None else now
    candidates=[]
    for item in sources:
        identity=post_identity(item.get('url',''))
        if not identity or identity[0]!=item.get('platform'):continue
        if not all(isinstance(item.get(k),str) and item[k].strip() for k in ('id','title')):continue
        _,age=publication(item.get('published_at'))
        if age is not None and not -2<=age<=365:continue
        record={k:v for k,v in item.items() if k not in ('evaluation','semantic_verified','intent','match_reason','match_level','retrieval_score')}
        record['url']=identity[1]
        candidates.append(record)
    candidates=merge_candidates(candidates)
    checked=cached_evaluations(project,candidates)
    cached={s['url'] for s in checked}
    candidates=balanced_candidates(project,[s for s in candidates if s['url'] not in cached],limit=limit)
    model=os.environ.get('OUTLOUD_GEMINI_MODEL','gemini-3.5-flash-lite')
    product=model_key(project);inserted=0
    with connect() as db:
        setup(db)
        for source in checked:
            db.execute("UPDATE evaluation_jobs SET state='complete',completed=?,error_type=NULL WHERE key=? AND lease_until<=?",
                       (now,evaluation_key(project,source,model),now))
        for source in candidates:
            key=evaluation_key(project,source,model)
            # A revised post/brief/policy needs its own decision. Pending obsolete
            # text must not compete with that revision for a worker slot.
            db.execute("UPDATE evaluation_jobs SET state='superseded',lease=NULL,lease_until=0 WHERE product_key=? AND url=? AND key!=? AND state IN ('pending','retry')",
                       (product,source['url'],key))
            inserted+=db.execute('INSERT OR IGNORE INTO evaluation_jobs(key,product_key,url,project,source,state,created,next_due,completed) VALUES(?,?,?,?,?,?,?,?,?)',
                (key,product,source['url'],json.dumps(project.model_dump()),json.dumps(source),'pending',now,now,None)).rowcount
    return {'queued':inserted,'candidates':len(candidates),'cached':len(cached),'provider_calls':0}


def enqueue_subscriptions(limit=20):
    """Bounded corpus reuse across products; never generates plans or embeddings."""
    from research_providers import remembered_candidates
    bounded(limit,100,'Inspect at most one hundred subscribed products.')
    with connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_subscriptions'").fetchone():
            return {'products':0,'queued':0,'provider_calls':0}
        rows=db.execute('SELECT key,project FROM collection_subscriptions ORDER BY updated,key').fetchall()
    # Older plan versions may have left subscription aliases for the same brief.
    # Count each current product once and advance every alias's queue scan time.
    products={}
    for subscription_key,raw in rows:
        project=stored_project(raw);key=model_key(project)
        if key not in products:products[key]={'project':project,'aliases':[]}
        products[key]['aliases'].append(subscription_key)
    queued=0
    selected=list(products.values())[:limit]
    for item in selected:
        project=item['project']
        queued+=enqueue(project,remembered_candidates(project,cached_only=True))['queued']
        with connect() as db:db.executemany('UPDATE collection_subscriptions SET updated=? WHERE key=?',[(time.time(),key) for key in item['aliases']])
    return {'products':len(selected),'queued':queued,'provider_calls':0}


def status(now=None):
    now=time.time() if now is None else now
    with connect() as db:
        setup(db)
        counts=dict(db.execute('SELECT state,COUNT(*) FROM evaluation_jobs GROUP BY state').fetchall())
        due=db.execute("SELECT COUNT(*) FROM evaluation_jobs WHERE (state IN ('pending','retry') AND next_due<=?) OR (state='running' AND lease_until<=?)",(now,now)).fetchone()[0]
        errors=dict(db.execute('SELECT error_type,COUNT(*) FROM evaluation_jobs WHERE error_type IS NOT NULL GROUP BY error_type').fetchall())
    return {'states':counts,'due':due,'errors':errors,'provider_calls':0,
            'execution_enabled':os.environ.get('OUTLOUD_EVALUATION_WORKER_ALLOWED')=='1',
            'note':'Queued candidates are not accepted recommendations.'}


def claim(limit,now):
    bounded(limit,4,'Evaluate one to four candidates per tick.')
    model=os.environ.get('OUTLOUD_GEMINI_MODEL','gemini-3.5-flash-lite')
    tasks=[];product=None;identifiers=set()
    with connect() as db:
        setup(db);db.execute('BEGIN IMMEDIATE')
        rows=db.execute("SELECT key,product_key,project,source FROM evaluation_jobs WHERE (state IN ('pending','retry') AND next_due<=?) OR (state='running' AND lease_until<=?) ORDER BY next_due,created,key LIMIT 500",(now,now)).fetchall()
        for key,product_key,raw,source_json in rows:
            if product is not None and product_key!=product:continue
            project=stored_project(raw);source=json.loads(source_json)
            if evaluation_key(project,source,model)!=key:
                db.execute("UPDATE evaluation_jobs SET state='superseded',lease=NULL,lease_until=0 WHERE key=?",(key,))
                continue
            if source['id'] in identifiers:continue
            product=product_key;identifiers.add(source['id']);lease=uuid.uuid4().hex
            db.execute("UPDATE evaluation_jobs SET state='running',lease=?,lease_until=?,attempts=attempts+1 WHERE key=?",(lease,now+LEASE_SECONDS,key))
            tasks.append({'key':key,'project':project,'source':source,'lease':lease})
            if len(tasks)>=limit:break
    return tasks


def run_once(limit=4,evaluator=None,now=None):
    """An explicit switch plus provider budget authorization precede paid work."""
    bounded(limit,4,'Evaluate one to four candidates per tick.')
    if os.environ.get('OUTLOUD_EVALUATION_WORKER_ALLOWED')!='1':
        return {'state':'disabled','evaluated':0,'completed':0,'failed':0,'provider_calls':0}
    fixed=now is not None;now=time.time() if now is None else now
    tasks=claim(limit,now)
    if not tasks:return {'state':'idle','evaluated':0,'completed':0,'failed':0,'provider_calls':0}
    results={};error=None
    try:
        # evaluate() rechecks its exact cache, reserves each model batch, and
        # persists validated decisions. It also reports partial batch failures.
        results=(evaluator or evaluate)(tasks[0]['project'],[t['source'] for t in tasks])
    except Exception as failure:
        error=type(failure).__name__
    completed=0;failed=0;finished=now if fixed else time.time()
    with connect() as db:
        for task in tasks:
            success=task['source']['id'] in results
            reason=None if success else error or 'DecisionUnavailable'
            row=db.execute('SELECT attempts FROM evaluation_jobs WHERE key=?',(task['key'],)).fetchone()
            attempts=row[0]
            delay=min(86400,3600*2**min(attempts-1,5))
            changed=db.execute('''UPDATE evaluation_jobs SET state=?,error_type=?,next_due=?,completed=?,lease=NULL,lease_until=0
              WHERE key=? AND lease=?''',('complete' if success else 'retry',reason,finished+delay,finished if success else None,task['key'],task['lease'])).rowcount
            if changed:
                if success:completed+=1
                else:failed+=1
    return {'state':'processed','evaluated':len(tasks),'completed':completed,'failed':failed,
            'errors':{error or 'DecisionUnavailable':failed} if failed else {}}
