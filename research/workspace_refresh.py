"""Incremental, network-free publication of already evaluated corpus records.

Unreviewed collection is an inbox, never an implicit customer recommendation.
This module cannot invoke a model or start media collection.
"""
from copy import deepcopy
from datetime import datetime, timezone
from live_discovery import merge_candidates, post_identity, revalidate_candidates
from research_providers import cached_evaluations, remembered_candidates
from research_quality import select_results,MAX_RESULTS,LANE_LIMITS,is_native_source


def refresh(project, snapshot, candidates=None, previous_snapshot=None, native_only=False, *, history=()):
    previous=snapshot.get('discover',[])+snapshot.get('conversations',[])+list(history)
    # The snapshot belongs to this exact project; the public corpus never carries
    # somebody else's verdict. Original text changes invalidate cached decisions.
    corpus=remembered_candidates(project,cached_only=True) if candidates is None else candidates
    if candidates is None:
        corpus = [*corpus, *reviewed_originals(project)]

    corpus=[{k:v for k,v in source.items() if k not in ('evaluation','semantic_verified','intent','match_reason','match_level')}
            for source in corpus if post_identity(source.get('url',''))]
    corpus=list({source['url']:source for source in corpus if not native_only or is_native_source(source)}.values())
    checked=cached_evaluations(project,corpus)
    checked_urls={source['url'] for source in checked}
    # Preserve valid previous results only when the underlying text is unchanged.
    current={source['url']:source for source in corpus}
    retained=[]
    for source in previous:
        replacement=current.get(source.get('url'))
        if replacement and (replacement.get('title'),replacement.get('summary'))!=(source.get('title'),source.get('summary')):
            continue
        if source.get('url') not in checked_urls:retained.append(source)
    selected,quality=select_results(project,revalidate_candidates(project,merge_candidates(checked+retained)),require_evaluation=True,native_only=native_only)
    baseline=previous_snapshot if previous_snapshot is not None else snapshot
    old_urls={source.get('url') for source in baseline.get('discover',[])+baseline.get('conversations',[])}
    result=deepcopy(snapshot)
    result['discover']=[source for source in selected if source['section']=='discover']
    result['conversations']=[source for source in selected if source['section']=='conversations']
    issues=snapshot.get('research_issues',[])
    if issues:
        quality['launch_ready']=False
        quality['blockers']=list(dict.fromkeys(quality['blockers']+issues))
    result['limit']=MAX_RESULTS
    result['lane_limits']=dict(LANE_LIMITS)
    result['quality_report']=quality
    for diagnostic in ('retrieval','evaluation_failures'):
        if diagnostic in snapshot.get('quality_report',{}):quality[diagnostic]=snapshot['quality_report'][diagnostic]
    result['coverage']={platform:sum(source['platform']==platform for source in selected)
                        for platform in ('Reddit','X','Instagram','TikTok')}
    result['refresh']={'checked_at':datetime.now(timezone.utc).isoformat(),
                       'mode':'cached_evaluations_only','pending_evaluation':len(corpus)-len(checked),
                       'new_result_ids':[source['id'] for source in selected if source['url'] not in old_urls],
                       'provider_calls':0,
                       'coverage':coverage(corpus,checked,selected)}
    return result


def reviewed_originals(project):
    """Restore explicitly reviewed posts even when lexical retrieval misses them."""
    import json
    from live_discovery import cache_key
    from research_retrieval import connect
    with connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='local_conversation_reviews'").fetchone():
            return []
        rows = db.execute(
            'SELECT s.data FROM local_conversation_reviews r JOIN public_sources s ON s.url=r.url '
            'WHERE r.profile_key=? LIMIT 20', (cache_key(project),)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def coverage(candidates, checked, selected):
    """Distinguish collection gaps from pending review and quality rejection."""
    result={}
    for platform in ('Instagram','TikTok','X','Reddit'):
        collected={s['url'] for s in candidates if s.get('platform')==platform}
        evaluated={s['url'] for s in checked if s.get('platform')==platform} & collected
        accepted={s['url'] for s in selected if s.get('platform')==platform} & collected
        result[platform]={'collected':len(collected),'evaluated':len(evaluated),
                          'accepted':len(accepted),'pending_evaluation':len(collected-evaluated),
                          'status':'has_matches' if accepted else 'needs_review' if collected-evaluated else 'no_qualified_matches' if collected else 'needs_collection'}
    return result


def archived(db, project_id, owner, project):
    """Read the owner's archive only when the exact current brief has checked the original."""
    import json
    from research_retrieval import connect
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='reference_history'").fetchone():return []
    rows=db.execute('SELECT h.data FROM reference_history h JOIN projects p ON p.id=h.project_id '
                    'WHERE h.project_id=? AND p.owner=?',(project_id,owner)).fetchall()
    records=[json.loads(row[0]) for row in rows]
    if not records:return []
    current={}
    with connect() as corpus:
        if corpus.execute("SELECT 1 FROM sqlite_master WHERE name='public_sources'").fetchone():
            for index in range(0,len(records),100):
                urls=[source['url'] for source in records[index:index+100]]
                for url,data in corpus.execute('SELECT url,data FROM public_sources WHERE url IN ('+
                                               ','.join('?' for _ in urls)+')',urls):
                    source=json.loads(data)
                    current[url]=(source.get('title'),source.get('summary'))
    unchanged=[source for source in records if current.get(source['url'],(source.get('title'),source.get('summary')))
               ==(source.get('title'),source.get('summary'))]
    return cached_evaluations(project,unchanged)


def archive(db,project_id,snapshot):
    """Owner-scoped history survives expiration from the fresh recommendations."""
    import json
    db.execute('CREATE TABLE IF NOT EXISTS reference_history(project_id TEXT,url TEXT,data TEXT,PRIMARY KEY(project_id,url))')
    for source in snapshot.get('discover',[])+snapshot.get('conversations',[]):
        if post_identity(source.get('url','')):
            db.execute('INSERT OR IGNORE INTO reference_history VALUES(?,?,?)',(project_id,source['url'],json.dumps(source)))


def publish_saved(limit=20):
    """Bounded local worker step. No provider calls; retain original posts in history.

    Uses the request path's lock and a snapshot compare-and-swap so a worker
    cannot overwrite a concurrently edited product or newer workspace.
    """
    import hashlib,json
    import app
    from live_discovery import cache_key,provider_cache_signature
    from product_profile import research_project
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=100:
        raise ValueError('Refresh at most 100 workspaces per step.')
    with app.connect() as db:
        rows=db.execute('SELECT id FROM projects ORDER BY created DESC LIMIT ?',(limit,)).fetchall()
    published=0;skipped=0
    for row in rows:
        with app.connect() as db:
            current=db.execute('SELECT * FROM projects WHERE id=?',(row['id'],)).fetchone()
            if current is None:continue
            snapshot=json.loads(current['results'])
            if not snapshot.get('quality_report'):skipped+=1;continue
            from pydantic import ValidationError
            try:project=app.project_from_record(json.loads(current['data']))
            except ValidationError:
                skipped+=1
                continue
            meta=db.execute('SELECT data FROM metadata_cache WHERE url=?',(project.url,)).fetchone() if project.url else None
        project=research_project(project,json.loads(meta['data']) if meta else {})
        with app.connect() as db:
            history=archived(db,row['id'],current['owner'],project)
        key=hashlib.sha256((current['owner']+str(app.SEARCH_VERSION)+cache_key(project)+provider_cache_signature()).encode()).hexdigest()
        with app.research_lock(key):
            updated=refresh(project,snapshot,history=history)
            with app.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                changed=db.execute('UPDATE projects SET results=? WHERE id=? AND data=? AND results=?',
                    (json.dumps(updated),current['id'],current['data'],current['results'])).rowcount
                if changed:
                    # Keep original retrieval age. Cached-only refresh must not
                    # indefinitely postpone a fresh search.
                    db.execute('UPDATE research_cache SET data=? WHERE key=?',(json.dumps(updated),key))
                    archive(db,current['id'],snapshot)
                    published+=1
                else:skipped+=1
    return {'published':published,'skipped':skipped,'provider_calls':0}
