import json
import pytest
import collect_public as collector
import research_retrieval as store
import app


def prepared(monkeypatch,tmp_path):
    monkeypatch.setattr(app,'DB',tmp_path/'app.sqlite3')
    project=app.Project(name='InvoiceTrail',platform='Web',status='unlaunched',category='business',description='Help freelancers chase overdue invoices.',competitors=['Invoice Ninja'])
    store.save_model(project,{'for_you':['chasing invoices'],'competitors':['invoice reminders'],'conversations':['unpaid invoices'],'subreddits':['freelance']})
    collector.subscribe(project)
    return project


def test_daily_and_three_day_schedules_and_no_read_spend(monkeypatch,tmp_path):
    prepared(monkeypatch,tmp_path)
    calls=[]
    for _ in range(2):
        result=collector.collect_once(4,lambda q,o:calls.append(q) or '',now=1000)
        assert result['succeeded']==4
    assert len(calls)==8
    assert collector.collect_once(4,lambda *a:pytest.fail('No duplicate check'),now=1001)['queries']==0
    report=collector.status(now=1000+86400)
    due=[c for c in report['checks'] if c['state']=='due']
    assert len(due)==2 and all(c['lane']=='conversations' for c in due)
    assert all(c['last_success']==1000 for c in report['checks'])
    assert len(collector.status(now=1000+259200)['checks'])==8


def test_failure_is_not_success_and_retries_are_delayed(monkeypatch,tmp_path):
    prepared(monkeypatch,tmp_path)
    def fail(*args):raise RuntimeError('private provider response must not be stored')
    result=collector.collect_once(1,fail,now=1000)
    assert result['failed']==1 and result['succeeded']==0
    checks=collector.status(now=1001)['checks']
    failed=next(c for c in checks if c['error_type'])
    assert failed['last_success'] is None
    assert failed['next_due']==4600 and failed['state']=='retry_wait'
    assert failed['error_type']=='RuntimeError'
    assert 'private' not in json.dumps(checks)
    with store.connect() as db:
        row=db.execute('SELECT cursor FROM collection_checks WHERE error_type IS NOT NULL').fetchone()
        assert row[0]==0


def test_claim_lease_prevents_duplicate_work_and_recovers_after_crash(monkeypatch,tmp_path):
    prepared(monkeypatch,tmp_path)
    tasks=collector.claim(4,1000,False)
    other=collector.claim(4,1000,False)
    keys=lambda rows:{(r['key'],r['lane'],r['platform']) for r in rows}
    assert not keys(tasks)&keys(other)
    assert collector.claim(4,1001,False)==[]
    recovered=collector.claim(4,1121,False)
    assert len(recovered)==4
    assert all(t['lease']!=r['lease'] for t in tasks for r in recovered)


def test_known_competitor_only_used_in_competitor_queries(monkeypatch,tmp_path):
    p=prepared(monkeypatch,tmp_path);model=store.cached_model(p)
    assert 'Invoice Ninja' in collector.plan_queries(p,model,'competitors','Instagram')[0]
    assert 'Invoice Ninja' not in collector.plan_queries(p,model,'for_you','Instagram')[0]
    assert collector.plan_queries(p,model,'conversations','Reddit')[0]=='community-feed:freelance'


def test_status_and_resubscription_do_not_reset_cadence(monkeypatch,tmp_path):
    p=prepared(monkeypatch,tmp_path)
    collector.collect_once(1,lambda *a:'',now=1000)
    before=collector.status(now=1001)
    collector.subscribe(p)
    assert collector.status(now=1001)==before


def test_global_daily_quota_failure_is_recorded_without_network(monkeypatch,tmp_path):
    prepared(monkeypatch,tmp_path)
    monkeypatch.setattr(app,'SEARCH_DAILY_LIMIT',0)
    result=collector.collect_once(1,lambda *a:pytest.fail('Quota must apply'),now=1000)
    assert result['failed']==1
    assert next(c for c in collector.status(now=1001)['checks'] if c['error_type'])['last_success'] is None


def test_tick_bounds():
    for value in (0,5,True,-1,1.5):
        with pytest.raises(ValueError):collector.collect_once(value)


def test_multiple_phrases_rotate_within_lane_refresh_window(monkeypatch,tmp_path):
    p=prepared(monkeypatch,tmp_path)
    store.save_model(p,{'conversations':['unpaid invoice reminders','late client payments','awkward payment followups'],'for_you':['freelancer routines'],'competitors':['invoice reminders']})
    calls=[]
    collector.collect_once(4,lambda q,o:calls.append(q) or '',now=1000)
    collector.collect_once(4,lambda q,o:calls.append(q) or '',now=1000)
    checks=collector.status(now=1001)['checks']
    checked=[c for c in checks if c['last_success']==1000 and c['lane']=='conversations']
    assert checked and all(c['next_due']==1000+86400/3 for c in checked)
    assert all(c['state']=='scheduled' for c in checked)
    assert all('after:' in q for q in calls)


def test_adjacent_topics_expand_creatives_only(monkeypatch,tmp_path):
    p=prepared(monkeypatch,tmp_path)
    model={**store.cached_model(p),'adjacent_topics':['freelancer daily routine']}
    assert any('freelancer daily routine' in q for q in collector.plan_queries(p,model,'for_you','TikTok'))
    assert not any('freelancer daily routine' in q for q in collector.plan_queries(p,model,'conversations','Reddit'))


def test_internal_metadata_context_survives_scheduler_restore(monkeypatch,tmp_path):
    p=prepared(monkeypatch,tmp_path)
    enriched=p.model_copy(update={'description':p.description+' Publisher details: '+('product context '*120)})
    store.save_model(enriched,{'for_you':['invoice chasing'],'competitors':['invoice reminders'],'conversations':['unpaid invoices']})
    collector.subscribe(enriched)
    report=collector.status(now=1000)
    assert len(report['checks'])==16
    raw=json.dumps(enriched.model_dump())
    assert store.model_key(collector.stored_project(raw))==store.model_key(enriched)
    assert collector.stored_project(raw).description==enriched.description
    with pytest.raises(ValueError):collector.stored_project(json.dumps({**p.model_dump(),'description':'x'*10001}))
