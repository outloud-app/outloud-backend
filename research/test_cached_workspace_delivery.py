"""Exercise the real browser endpoint with an empty legacy project snapshot."""
import json
import time
from datetime import datetime, timezone
from fastapi.testclient import TestClient
import app
import research_providers as providers
from research_retrieval import connect


def test_empty_project_opens_verified_corpus_without_network_and_survives_restart(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'DB',tmp_path/'trial.sqlite3')
    monkeypatch.setattr(app,'STREAM_JOBS',{})
    monkeypatch.setattr(app,'LIVE_SEARCH',False)
    monkeypatch.setenv('OUTLOUD_RESEARCH_CACHE_ONLY','1')
    monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','1')
    monkeypatch.setenv('GEMINI_API_KEY','placeholder')
    monkeypatch.setenv('OUTLOUD_GEMINI_MODEL','fixture-model')
    def forbidden(*args,**kwargs):raise AssertionError('Cached workspace opening cannot start provider work')
    for function in ('search_brief','evaluate','enrich_media','authorize'):
        monkeypatch.setattr(providers,function,forbidden)
    import httpx
    monkeypatch.setattr(httpx,'post',forbidden)
    brief={'name':'Study','platform':'iOS','status':'unlaunched','category':'productivity',
           'description':'An app that helps students remember exam revision schedules.'}
    now=datetime.now(timezone.utc).isoformat()
    source={'id':'help','url':'https://reddit.com/r/studying/comments/abc/revision/',
            'title':'Does anyone know an exam revision planner?',
            'summary':'I need an app to remember my exam revision schedule.',
            'platform':'Reddit','kind':'Discussion','author':'student','published_at':now,
            'evidence':{'type':'original_platform_post','provider':'apify'}}
    providers.remember_public_sources([source])
    verdict={'provider':'gemini','policy_version':providers.EVALUATION_VERSION,'checked_at':now,
             'intent':'audience_problem','need_status':'unresolved','need_type':'software_recommendation','relevance':.95,
             'request_quote':source['summary'],'evidence_quote':source['summary'],'reason':'Revision scheduling problem.'}
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS semantic_decisions(key TEXT PRIMARY KEY,data TEXT,created REAL)')
        db.execute('INSERT INTO semantic_decisions VALUES(?,?,?)',
                   (providers.evaluation_key(app.Project(**brief),source,'fixture-model'),json.dumps(verdict),time.time()))
    with TestClient(app.app,headers={'Origin':'http://127.0.0.1:4321'}) as client:
        client.post('/session')
        identifier=client.post('/research',json=brief).json()['id']
        with app.connect() as db:
            db.execute('UPDATE projects SET results=? WHERE id=?',
                       (json.dumps({'discover':[],'conversations':[],'match_version':2}),identifier))
        monkeypatch.setattr(app,'LIVE_SEARCH',True)
        for attempt in range(2):
            app.STREAM_JOBS.clear()
            response=client.post(f'/projects/{identifier}/stream')
            assert response.status_code==200
            for _ in range(100):
                payload=client.get(f'/projects/{identifier}/stream').json()
                if payload['status']!='running':break
                time.sleep(.01)
            assert payload['status']=='complete',payload
            assert payload['workspace']['results']['conversations'][0]['id']=='help'
        with app.connect() as db:
            result=json.loads(db.execute('SELECT results FROM projects WHERE id=?',(identifier,)).fetchone()['results'])
        assert result['refresh']['provider_calls']==0
        assert not result['quality_report']['launch_ready']
        assert client.get('/health').json()['search_provider']=='collected_store'
