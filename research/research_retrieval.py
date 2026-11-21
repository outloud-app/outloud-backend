"""Reusable public corpus and bounded retrieval. No background paid collection."""
import hashlib
import json
import math
import os
import sqlite3
import statistics
import time
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit
import httpx


@contextmanager
def connect():
    path=Path(os.environ.get('OUTLOUD_PROVIDER_CACHE',str(Path(__file__).parent/'.data/provider-media.sqlite3')))
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS research_models(key TEXT PRIMARY KEY,data TEXT,created REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS embeddings(key TEXT PRIMARY KEY,data TEXT,created REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS engagement_observations(url TEXT,cohort TEXT,observed REAL,views REAL,likes REAL,comments REAL,PRIMARY KEY(url,observed))')
    try:
        with db:yield db
    finally:db.close()


def model_key(project):
    return hashlib.sha256(('problem-model-v5:'+json.dumps(project.model_dump(),sort_keys=True)).encode()).hexdigest()


def cached_model(project):
    with connect() as db:
        row=db.execute('SELECT data FROM research_models WHERE key=?',(model_key(project),)).fetchone()
    if row:return json.loads(row[0])
    if getattr(project, 'followed_sources', []):
        # A watchlist change does not require buying the same product understanding again.
        base=cached_model(project.model_copy(update={'followed_sources': []}))
        if base:
            return {key:value for key,value in base.items() if not key.startswith(('native_x_query_plan','native_reddit_query_plan'))}
    return None


def save_model(project,model):
    with connect() as db:db.execute('INSERT OR REPLACE INTO research_models VALUES(?,?,?)',(model_key(project),json.dumps(model),time.time()))


def cohort(source):
    path=urlsplit(source['url']).path.strip('/').split('/')
    # Communities for Reddit; creator baselines for social accounts. Never mix networks.
    identity=path[1] if source['platform']=='Reddit' and len(path)>1 and path[0]=='r' else source.get('author','')
    return source['platform']+':'+identity.lower()


def observe(sources):
    from datetime import datetime
    with connect() as db:
        for source in sources:
            metrics=source.get('metrics') or {}
            if not metrics.get('provider') or not metrics.get('checked_at'):continue
            try:stamp=datetime.fromisoformat(metrics['checked_at'].replace('Z','+00:00')).timestamp()
            except (ValueError,TypeError):continue
            def number(key):
                value=metrics.get(key)
                return value if isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else None
            db.execute('INSERT OR IGNORE INTO engagement_observations VALUES(?,?,?,?,?,?)',(source['url'],cohort(source),stamp,number('views'),number('likes'),number('comments')))


def relative_attention(source):
    """Comparable post-age cohort, minimum ten peers. Growth needs two real observations."""
    from datetime import datetime,timezone
    metrics=source.get('metrics') or {}
    result={'status':'insufficient_baseline','reason':'Not enough comparable measured posts yet.'}
    with connect() as db:
        rows=db.execute('SELECT data FROM public_sources WHERE url!=?',(source['url'],)).fetchall() if db.execute("SELECT 1 FROM sqlite_master WHERE name='public_sources'").fetchone() else []
        previous=db.execute('SELECT observed,views FROM engagement_observations WHERE url=? AND views IS NOT NULL ORDER BY observed',(source['url'],)).fetchall()
    def age(item):
        try:
            published=item.get('published_at')
            if not isinstance(published,str):return None
            return max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(published.replace('Z','+00:00'))).days)
        except (KeyError,ValueError,TypeError):return None
    own_age=age(source)
    peers=[json.loads(row[0]) for row in rows]
    peers=[s for s in peers if cohort(s)==cohort(source) and own_age is not None and age(s) is not None and abs(age(s)-own_age)<=max(7,own_age*.25)]
    for metric in ('views','plays','likes','comments','score'):
        values=[(s.get('metrics') or {}).get(metric) for s in peers if (s.get('metrics') or {}).get('provider') and (s.get('metrics') or {}).get('checked_at')]
        values=[v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0]
        own=metrics.get(metric)
        if len(values)>=10 and isinstance(own,(int,float)) and not isinstance(own,bool) and math.isfinite(own) and own>=0:
            baseline=statistics.median(values)
            if baseline>0:result={'status':'measured','metric':metric,'ratio':round(own/baseline,3),'baseline':baseline,'sample_size':len(values),'reason':'Compared with measured posts from the same community or creator at a similar post age.'};break
    if len(previous)>=2 and previous[-1][0]-previous[0][0]>=3600 and previous[-1][1]>=previous[0][1]:
        rate=(previous[-1][1]-previous[0][1])/((previous[-1][0]-previous[0][0])/3600)
        result['views_per_hour']=round(rate,2)
        # Compare growth only with measured observations in this same cohort.
        # A single lifetime view count cannot establish a growth rate.
        with connect() as db:
            observations=db.execute('SELECT url,observed,views FROM engagement_observations WHERE cohort=? AND url!=? AND views IS NOT NULL ORDER BY observed',(cohort(source),source['url'])).fetchall()
        groups={}
        peer_urls={s['url'] for s in peers}
        for url,stamp,views in observations:
            if url in peer_urls:groups.setdefault(url,[]).append((stamp,views))
        rates=[]
        for values in groups.values():
            if len(values)<2:continue
            duration=values[-1][0]-values[0][0]
            if duration>=3600 and values[-1][1]>=values[0][1]:rates.append((values[-1][1]-values[0][1])/(duration/3600))
        if len(rates)>=5 and statistics.median(rates)>0:
            result.update(growth_ratio=round(rate/statistics.median(rates),3),growth_baseline=statistics.median(rates),growth_sample_size=len(rates))
    return result


def embed(texts,task):
    from research_providers import authorize,ProviderNotConfigured
    key=os.environ.get('GEMINI_API_KEY')
    if not key:raise ProviderNotConfigured('Embeddings require Gemini API access.')
    model='gemini-embedding-001'
    texts=[text[:12000] for text in texts]
    keys=[hashlib.sha256(json.dumps([model,task,768,text]).encode()).hexdigest() for text in texts]
    found={}
    with connect() as db:
        for key_hash in keys:
            row=db.execute('SELECT data FROM embeddings WHERE key=?',(key_hash,)).fetchone()
            if row:found[key_hash]=json.loads(row[0])
    missing=list(dict.fromkeys(k for k in keys if k not in found))
    for start in range(0,len(missing),32):
        batch=missing[start:start+32]
        authorize('gemini-embeddings',10000)
        response=httpx.post('https://generativelanguage.googleapis.com/v1beta/models/'+model+':batchEmbedContents',headers={'x-goog-api-key':key},json={'requests':[{'model':'models/'+model,'content':{'parts':[{'text':texts[keys.index(k)]} ]},'taskType':task,'outputDimensionality':768} for k in batch]},timeout=30)
        response.raise_for_status()
        vectors=response.json().get('embeddings',[])
        if len(vectors)!=len(batch):raise ValueError('Incomplete embedding batch')
        with connect() as db:
            for k,item in zip(batch,vectors):
                vector=item.get('values',[])
                if len(vector)!=768 or not all(isinstance(v,(float,int)) and math.isfinite(v) for v in vector):raise ValueError('Invalid embedding')
                found[k]=vector
                db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?)',(k,json.dumps(vector),time.time()))
    return [found[k] for k in keys]


def retrieval_queries(project):
    """Independent query intent; creative recall must not inherit lead strictness."""
    from product_profile import research_context
    context=research_context(project)
    model=cached_model(project) or {}
    topics='; '.join(model.get('adjacent_topics',[])[:8])
    seeds='; '.join(context.get('research_keywords', []) + [s['name'] for s in context.get('followed_sources', []) if s['kind']=='topic'])
    seed_context='\nUser research topics (exploration hints, not confirmed product capabilities): '+seeds if seeds else ''
    return {
        'discover': 'Creative inspiration for audience: '+context['audience']+'\nNiche and product context: '+context['publisher_context']+'\nRelated topics: '+topics+seed_context+'\nEducation, demonstrations, entertaining experiences and routines for this audience.',
        'competitors': 'Products performing this customer job: '+context['product_job']+'\nKnown competitors: '+'; '.join(context['known_competitors'])+'\nPosts demonstrating or promoting competing products.',
        'conversations': 'Audience: '+context['audience']+'\nUnmet need: '+context['customer_problem']+seed_context+'\nRecent requests for recommendations, frustrations, complaints and workarounds.'}


def shortlist(project,sources,limit=90):
    """Cheap freshness/duplicate gates precede lane-specific semantic retrieval."""
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=100:
        raise ValueError('Shortlist must contain one to one hundred candidates.')
    from live_discovery import publication,merge_candidates,problem_match
    from research_quality import route_source
    from research_providers import ProviderNotConfigured
    from provider_budget import BudgetExceeded
    candidates=[]
    for source in merge_candidates(sources):
        _,age=publication(source.get('published_at'))
        lane=route_source(source)
        if age is not None and not -2<=age<=365:continue
        # Retrieved engagement does not make an old help request current.
        # Filter it before buying embeddings/evaluation, not after both costs.
        if lane=='conversations' and (age is None or age>30):continue
        candidates.append(source)
    candidates=sorted(candidates,key=lambda s:len(problem_match(project,s['title']+' '+s.get('summary',''))[0]),reverse=True)[:300]
    mode='lexical_fallback'
    if candidates:
        try:
            queries=retrieval_queries(project)
            lanes=list(dict.fromkeys(route_source(s) if route_source(s) in queries else 'conversations' for s in candidates))
            query_vectors=dict(zip(lanes,embed([queries[lane] for lane in lanes],'RETRIEVAL_QUERY')))
            vectors=embed([s['title']+'\n'+s.get('summary','') for s in candidates],'RETRIEVAL_DOCUMENT')
            for source,vector in zip(candidates,vectors):
                lane=route_source(source)
                query=query_vectors[lane if lane in query_vectors else 'conversations']
                norm=math.sqrt(sum(v*v for v in query))
                score=sum(a*b for a,b in zip(query,vector))/(norm*math.sqrt(sum(v*v for v in vector)) or 1)
                source['retrieval_score']=score
            mode='embeddings'
            candidates.sort(key=lambda s:s['retrieval_score'],reverse=True)
        except (httpx.HTTPError,ValueError,RuntimeError,ProviderNotConfigured,BudgetExceeded):pass
    # Preserve all three lanes instead of allowing competitor pitches to consume the shortlist.
    chosen=[]
    for lane in ('conversations','discover','competitors'):
        pool=[s for s in candidates if route_source(s)==lane]
        platforms=list(dict.fromkeys(s['platform'] for s in pool))
        groups=[[s for s in pool if s['platform']==platform] for platform in platforms]
        # One prolific platform must not consume a lane before the semantic
        # evaluator can inspect useful sources from the other networks.
        balanced=[]
        for index in range(len(pool)):
            for group in groups:
                if index<len(group):balanced.append(group[index])
            if len(balanced)>=limit//3:break
        chosen.extend(balanced[:limit//3])
    chosen.extend(s for s in candidates if s not in chosen)
    return chosen[:limit],{'mode':mode,'query_strategy':'audience_topics / competing_products / unmet_needs','collected_candidates':len(sources),'eligible_candidates':len(candidates),'shortlisted':min(limit,len(chosen))}


def public_search_index(db):
    """Index public post text only. No briefs, owners, verdicts or saved notes."""
    db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS public_source_search USING fts5(url UNINDEXED, text, tokenize="unicode61")')
    # One-time backfill when upgrading an existing corpus.
    if not db.execute('SELECT 1 FROM public_source_search LIMIT 1').fetchone():
        for url,raw in db.execute('SELECT url,data FROM public_sources'):
            row=json.loads(raw)
            db.execute('INSERT INTO public_source_search(url,text) VALUES(?,?)',
                       (url,' '.join(str(row.get(k,'')) for k in ('title','summary','author','community'))))


def public_candidate_rows(db,project,model=None):
    """Retrieve topic matches across the corpus, plus recent synonym candidates.

    Do not let the newest 2,000 unrelated posts hide an older relevant niche.
    FTS retrieves candidates; it never authorizes publication into a workspace.
    """
    from product_profile import terms
    public_search_index(db)
    model=model or {}
    inputs=[*[source.name for source in getattr(project,'followed_sources',[])],*getattr(project,'keywords',[]),*model.get('adjacent_topics',[]),project.audience,project.problem,project.description]
    tokens=list(dict.fromkeys(token for value in inputs for token in sorted(terms(str(value)))))[:48]
    cutoff=time.time()-7776000
    matched=[]
    if tokens:
        expression=' OR '.join('"'+t.replace('"','""')+'"' for t in tokens)
        matched=db.execute('''SELECT p.data FROM public_source_search
          JOIN public_sources p ON p.url=public_source_search.url
          WHERE public_source_search MATCH ? AND p.created>?
          ORDER BY bm25(public_source_search),p.created DESC LIMIT 600''',(expression,cutoff)).fetchall()
    recent=db.execute('SELECT data FROM public_sources WHERE created>? ORDER BY created DESC LIMIT 400',(cutoff,)).fetchall()
    return list(dict.fromkeys(row[0] for row in matched+recent))
