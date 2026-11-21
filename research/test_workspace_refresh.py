import json
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import pytest
import app
import workspace_refresh as module
from demo_access import demo_results


def product():
    return app.Project(name='Meal Log',platform='iOS',status='unlaunched',category='fitness',
                       description='Photo food calorie tracking for people tired of manual food logging.')


def post(identifier='abc',days=0):
    text='Does anyone know a food calorie tracker? I am tired of manual food logging every day.'
    return {'id':identifier,'url':f'https://www.reddit.com/r/caloriecount/comments/{identifier}/post/',
            'title':'Does anyone know a food calorie tracker?','summary':text,'author':'someone',
            'platform':'Reddit','kind':'Discussion','published_at':(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()}


def reviewed(source,intent='audience_problem'):
    result=deepcopy(source)
    result['evaluation']={'provider':'gemini','checked_at':datetime.now(timezone.utc).isoformat(),
                          'intent':intent,'relevance':.95,'evidence_quote':source['summary'],
                          'request_quote':source['summary'],'need_status':'unresolved'}
    return result


def workspace(sources=()):
    return {'discover':[],'conversations':list(sources),'quality_report':{'blockers':[]},'coverage':{}}


def test_unreviewed_or_foreign_verdict_cannot_be_published(monkeypatch):
    candidate=reviewed(post()) # A verdict attached to the shared input is untrusted.
    monkeypatch.setattr(module,'cached_evaluations',lambda p,sources:[])
    result=module.refresh(product(),workspace(),[candidate])
    assert result['conversations']==[]
    assert result['refresh']['pending_evaluation']==1
    assert result['refresh']['provider_calls']==0


def test_checked_new_source_appears_once_and_snapshot_is_not_mutated(monkeypatch):
    candidate=post()
    monkeypatch.setattr(module,'cached_evaluations',lambda p,sources:[reviewed(s) for s in sources])
    snapshot=workspace();before=deepcopy(snapshot)
    result=module.refresh(product(),snapshot,[candidate])
    assert [s['id'] for s in result['conversations']]==['abc']
    assert result['refresh']['new_result_ids']==['abc']
    assert snapshot==before
    again=module.refresh(product(),result,[candidate])
    assert again['refresh']['new_result_ids']==[]


def test_fresh_rejection_overrides_prior_acceptance(monkeypatch):
    candidate=post();old=reviewed(candidate)
    monkeypatch.setattr(module,'cached_evaluations',lambda p,sources:[reviewed(s,'irrelevant') for s in sources])
    result=module.refresh(product(),workspace([old]),[candidate])
    assert result['conversations']==[]


def test_changed_source_text_requires_new_decision(monkeypatch):
    candidate=post();changed={**candidate,'summary':candidate['summary']+' Now promoting my new meal tool.'}
    monkeypatch.setattr(module,'cached_evaluations',lambda p,sources:[])
    result=module.refresh(product(),workspace([reviewed(candidate)]),[changed])
    assert not result['conversations'] and result['refresh']['pending_evaluation']==1


def test_old_leads_expire_and_collection_issues_do_not_disappear(monkeypatch):
    monkeypatch.setattr(module,'cached_evaluations',lambda p,sources:[])
    snapshot=workspace([reviewed(post(days=31))]);snapshot['research_issues']=['X collection unavailable.']
    result=module.refresh(product(),snapshot,[])
    assert not result['conversations'] and not result['quality_report']['launch_ready']
    assert 'X collection unavailable.' in result['quality_report']['blockers']
    assert 'refresh' not in demo_results(result)


def test_worker_preserves_project_and_archives_removed_references_without_network(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'DB',tmp_path/'trial.sqlite3')
    monkeypatch.setattr(module,'remembered_candidates',lambda p,**kwargs:[])
    monkeypatch.setattr(module,'cached_evaluations',lambda p,sources:[])
    p=product();old=reviewed(post(days=31));snapshot=workspace([old])
    with app.connect() as db:
        db.execute('INSERT INTO projects(id,owner,data,results,created,rating,review) VALUES(?,?,?,?,?,?,?)',
                   ('project','owner',json.dumps(p.model_dump()),json.dumps(snapshot),1,4,'Useful'))
    result=module.publish_saved()
    assert result=={'published':1,'skipped':0,'provider_calls':0}
    with app.connect() as db:
        row=db.execute('SELECT * FROM projects').fetchone()
        assert json.loads(row['data'])==p.model_dump()
        assert row['rating']==4 and row['review']=='Useful'
        assert not json.loads(row['results'])['conversations']
        assert db.execute('SELECT COUNT(*) FROM reference_history').fetchone()[0]==1
    module.publish_saved()
    with app.connect() as db:assert db.execute('SELECT COUNT(*) FROM reference_history').fetchone()[0]==1


def test_worker_bounded():
    for value in (0,101,True,1.5):
        with pytest.raises(ValueError):module.publish_saved(value)


def test_worker_does_not_overwrite_concurrent_project_edit(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'DB',tmp_path/'trial.sqlite3')
    p=product();snapshot=workspace([reviewed(post())])
    with app.connect() as db:
        db.execute('INSERT INTO projects(id,owner,data,results,created) VALUES(?,?,?,?,?)',
                   ('project','owner',json.dumps(p.model_dump()),json.dumps(snapshot),1))
    def concurrent_edit(project,results,**kwargs):
        with app.connect() as db:
            db.execute('UPDATE projects SET data=? WHERE id=?',(json.dumps({**p.model_dump(),'name':'Edited'}),'project'))
        return workspace()
    monkeypatch.setattr(module,'refresh',concurrent_edit)
    assert module.publish_saved()['skipped']==1
    with app.connect() as db:
        row=db.execute('SELECT * FROM projects').fetchone()
        assert json.loads(row['data'])['name']=='Edited'
        assert json.loads(row['results'])==snapshot


def test_reopening_current_cache_refreshes_without_new_search(tmp_path,monkeypatch):
    import hashlib,time
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app,'DB',tmp_path/'trial.sqlite3')
    monkeypatch.setattr(app,'LIVE_SEARCH',False)
    candidate=post()
    monkeypatch.setattr(module,'remembered_candidates',lambda p,**kwargs:[candidate])
    monkeypatch.setattr(module,'cached_evaluations',lambda p,sources:[reviewed(s) for s in sources])
    def forbidden(*args,**kwargs):pytest.fail('A saved-workspace refresh must not start research')
    monkeypatch.setattr(app,'research_live',forbidden)
    headers={'origin':'http://127.0.0.1:4321','host':'127.0.0.1:8766'}
    with TestClient(app.app,headers=headers) as client:
        client.post('/session')
        identifier=client.post('/research',json=product().model_dump()).json()['id']
        with app.connect() as db:
            row=db.execute('SELECT * FROM projects WHERE id=?',(identifier,)).fetchone()
            p=app.research_project(product(),{})
            key=hashlib.sha256((row['owner']+str(app.SEARCH_VERSION)+app.cache_key(p)+app.provider_cache_signature()).encode()).hexdigest()
            db.execute('INSERT OR REPLACE INTO research_cache VALUES(?,?,?)',(key,json.dumps(workspace()),time.time()))
        monkeypatch.setattr(app,'LIVE_SEARCH',True)
        response=client.get('/projects/'+identifier)
        assert response.status_code==200
        assert response.json()['results']['conversations'][0]['id']=='abc'
        assert 'refresh' not in response.json()['results']
        with app.connect() as db:
            result=json.loads(db.execute('SELECT results FROM projects WHERE id=?',(identifier,)).fetchone()[0])
            assert result['refresh']['new_result_ids']==['abc']
        assert client.get('/projects/'+identifier).status_code==200
        with app.connect() as db:
            result=json.loads(db.execute('SELECT results FROM projects WHERE id=?',(identifier,)).fetchone()[0])
            assert result['refresh']['new_result_ids']==[]
    with TestClient(app.app,headers=headers) as other:
        other.post('/session')
        assert other.get('/projects/'+identifier).status_code==404
