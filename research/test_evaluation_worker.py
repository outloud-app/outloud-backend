"""Offline worker contracts, including collection-to-publication integration."""
import json
from datetime import datetime,timezone,timedelta
import pytest
import app
import evaluation_worker as worker
import research_providers as providers
from research_retrieval import connect


def product(name='Meal Log'):
    return app.Project(name=name,platform='iOS',status='unlaunched',category='fitness',
                       description='Photo food calorie tracking for people tired of manual food logging.')


def source(number=1):
    text='Does anyone know a food calorie tracker? I am tired of manual food logging every day.'
    return {'id':f'post-{number}','url':f'https://www.reddit.com/r/caloriecount/comments/abc{number}/post/',
            'title':'Does anyone know a food calorie tracker?','summary':text,'author':'someone',
            'platform':'Reddit','kind':'Discussion','published_at':datetime.now(timezone.utc).isoformat()}


def verdict(item,intent='audience_problem'):
    return {'provider':'gemini','checked_at':datetime.now(timezone.utc).isoformat(),'intent':intent,
            'relevance':.95,'evidence_quote':item['summary'],'request_quote':item['summary'],'need_status':'unresolved'}


def enabled(monkeypatch):
    monkeypatch.setenv('OUTLOUD_EVALUATION_WORKER_ALLOWED','1')
    monkeypatch.setenv('GEMINI_API_KEY','offline-test-placeholder')


def test_disabled_worker_never_claims_or_calls_provider(monkeypatch):
    worker.enqueue(product(),[source()],now=1000)
    monkeypatch.delenv('OUTLOUD_EVALUATION_WORKER_ALLOWED',raising=False)
    assert worker.run_once(evaluator=lambda *a:pytest.fail('Paid work disabled'),now=1000)['state']=='disabled'
    assert worker.status(now=1000)['states']=={'pending':1}


def test_queue_canonicalizes_deduplicates_and_discards_foreign_verdicts():
    item={**source(),'evaluation':{'intent':'creative_reference'},'semantic_verified':True,'match_reason':'Not trusted'}
    assert worker.enqueue(product(),[item,item],now=1000)['queued']==1
    assert worker.enqueue(product(),[item],now=1000)['queued']==0
    with connect() as db:
        stored=json.loads(db.execute('SELECT source FROM evaluation_jobs').fetchone()[0])
    assert not {'evaluation','semantic_verified','match_reason'}&stored.keys()


def test_invalid_and_expired_originals_are_not_queued():
    old={**source(2),'published_at':(datetime.now(timezone.utc)-timedelta(days=400)).isoformat()}
    invalid={**source(3),'url':'https://example.org/not-original'}
    assert worker.enqueue(product(),[old,invalid],now=1000)['candidates']==0


def test_capacity_is_not_six_candidates_per_platform():
    assert worker.enqueue(product(),[source(i) for i in range(100)],limit=90,now=1000)['queued']==90


def test_atomic_leases_and_expired_worker_recovery():
    worker.enqueue(product(),[source(i) for i in range(6)],now=1000)
    first=worker.claim(4,1000);second=worker.claim(4,1000)
    assert len(first)==4 and len(second)==2
    assert not {t['key'] for t in first}&{t['key'] for t in second}
    assert worker.claim(4,1001)==[]
    assert len(worker.claim(4,1000+worker.LEASE_SECONDS+1))==4


def test_different_products_do_not_share_decisions_or_batches():
    for name in ('Meal Log','Calorie Journal'):worker.enqueue(product(name),[source()],now=1000)
    a=worker.claim(4,1000);b=worker.claim(4,1000)
    assert len(a)==len(b)==1 and a[0]['key']!=b[0]['key']
    assert a[0]['project'].name!=b[0]['project'].name


def test_changed_text_supersedes_pending_old_decision():
    worker.enqueue(product(),[source()],now=1000)
    changed={**source(),'summary':'I now promote my own new calorie tracking app.'}
    worker.enqueue(product(),[changed],now=1001)
    assert worker.status(now=1001)['states']=={'pending':1,'superseded':1}
    assert worker.claim(4,1001)[0]['source']['summary']==changed['summary']


def test_changed_policy_does_not_evaluate_obsolete_job(monkeypatch):
    worker.enqueue(product(),[source()],now=1000)
    monkeypatch.setattr(providers,'EVALUATION_VERSION',providers.EVALUATION_VERSION+1)
    assert worker.claim(4,1001)==[]
    assert worker.status(now=1001)['states']=={'superseded':1}


def test_failure_is_delayed_and_raw_error_is_not_exposed(monkeypatch):
    enabled(monkeypatch);worker.enqueue(product(),[source()],now=1000)
    def broken(*a):raise RuntimeError('secret provider body')
    report=worker.run_once(evaluator=broken,now=1000)
    assert report['failed']==1 and report['completed']==0
    assert worker.status(now=1001)['due']==0
    assert worker.claim(4,4599)==[]
    assert len(worker.claim(4,4600))==1
    assert 'secret' not in json.dumps(worker.status(now=1001))


def test_partial_evaluation_caches_success_and_retries_only_missing(monkeypatch):
    enabled(monkeypatch);p=product()
    worker.enqueue(p,[source(),source(2)],now=1000)
    monkeypatch.setattr(providers,'evaluate_batch',lambda p,items:{items[0]['id']:verdict(items[0])})
    result=worker.run_once(now=1000)
    assert (result['completed'],result['failed'])==(1,1)
    assert worker.status(now=1001)['states']=={'complete':1,'retry':1}
    assert len(providers.cached_evaluations(p,[source(),source(2)]))==1


def test_new_collected_post_becomes_saved_workspace_result_without_research_restart(monkeypatch,tmp_path):
    from workspace_refresh import publish_saved
    enabled(monkeypatch);monkeypatch.setattr(app,'DB',tmp_path/'app.sqlite3')
    p=product();item=source()
    providers.remember_public_sources([item])
    snapshot={'discover':[],'conversations':[],'quality_report':{'blockers':[]}}
    with app.connect() as db:
        db.execute('INSERT INTO projects(id,owner,data,results,created) VALUES(?,?,?,?,?)',
                   ('project','owner',json.dumps(p.model_dump()),json.dumps(snapshot),1))
    worker.enqueue(p,[item],now=1000)
    calls=[]
    def inspect(project,items):
        calls.append(len(items))
        return {s['id']:verdict(s) for s in items}
    monkeypatch.setattr(providers,'evaluate_batch',inspect)
    assert worker.run_once(now=1000)['completed']==1
    assert publish_saved()['published']==1
    with app.connect() as db:results=json.loads(db.execute('SELECT results FROM projects').fetchone()['results'])
    from live_discovery import post_identity
    assert results['conversations'][0]['url']==post_identity(item['url'])[1]
    assert results['refresh']['new_result_ids']==[item['id']]
    assert worker.enqueue(p,[item],now=1001)['queued']==0
    assert worker.run_once(now=1001)['state']=='idle'
    assert calls==[1]


def test_provider_authorization_still_applies_when_worker_enabled(monkeypatch):
    enabled(monkeypatch);monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','0')
    monkeypatch.setattr(providers.httpx,'post',lambda *a,**k:pytest.fail('No paid provider permission'))
    worker.enqueue(product(),[source()],now=1000)
    assert worker.run_once(now=1000)['failed']==1
    assert worker.status(now=1001)['states']=={'retry':1}


def test_completed_rejection_is_reused_and_never_published(monkeypatch):
    from workspace_refresh import refresh
    enabled(monkeypatch);p=product();item=source()
    worker.enqueue(p,[item],now=1000)
    monkeypatch.setattr(providers,'evaluate_batch',lambda p,items:{s['id']:verdict(s,'irrelevant') for s in items})
    assert worker.run_once(now=1000)['completed']==1
    assert worker.enqueue(p,[item],now=1001)['queued']==0
    snapshot={'discover':[],'conversations':[],'quality_report':{'blockers':[]}}
    assert refresh(p,snapshot,[item])['conversations']==[]


def test_budget_exhaustion_cannot_start_network_request(monkeypatch):
    enabled(monkeypatch);monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','1')
    monkeypatch.setenv('OUTLOUD_EVALUATION_BUDGET_MICROUSD','1')
    monkeypatch.setattr(providers.httpx,'post',lambda *a,**k:pytest.fail('Budget rejected before network'))
    worker.enqueue(product(),[source()],now=1000)
    result=worker.run_once(now=1000)
    assert result['failed']==1 and result['completed']==0
    assert providers.cached_evaluations(product(),[source()])==[]


def test_subscription_inbox_rotates_products_without_provider_calls(monkeypatch):
    from collect_public import subscribe
    for name in ('Meal Log','Calorie Journal'):subscribe(product(name))
    monkeypatch.setattr(providers,'remembered_candidates',lambda p,**kw:[source()])
    monkeypatch.setattr(providers,'evaluate',lambda *a:pytest.fail('Queueing is local only'))
    assert worker.enqueue_subscriptions(limit=1)['queued']==1
    assert worker.enqueue_subscriptions(limit=1)['queued']==1
    with connect() as db:assert db.execute('SELECT COUNT(DISTINCT product_key) FROM evaluation_jobs').fetchone()[0]==2


def test_late_worker_cannot_overwrite_reclaimed_lease(monkeypatch):
    enabled(monkeypatch);worker.enqueue(product(),[source()],now=1000)
    def late(project,items):
        assert len(worker.claim(4,1000+worker.LEASE_SECONDS+1))==1
        return {s['id']:verdict(s) for s in items}
    result=worker.run_once(evaluator=late,now=1000)
    assert result['completed']==0
    assert worker.status(now=1001)['states']=={'running':1}


def test_old_subscription_aliases_do_not_starve_other_products(monkeypatch):
    from collect_public import subscribe
    p=product();subscribe(p);subscribe(product('Calorie Journal'))
    with connect() as db:
        db.execute('INSERT INTO collection_subscriptions(key,project) VALUES(?,?)',('legacy-alias',json.dumps(p.model_dump())))
    seen=[]
    monkeypatch.setattr(providers,'remembered_candidates',lambda p,**kw:seen.append(p.name) or [])
    worker.enqueue_subscriptions(limit=1);worker.enqueue_subscriptions(limit=1)
    assert set(seen)=={'Meal Log','Calorie Journal'}


@pytest.mark.parametrize('limit',[0,5,True,1.5])
def test_worker_tick_bounds(limit):
    with pytest.raises(ValueError):worker.run_once(limit)
