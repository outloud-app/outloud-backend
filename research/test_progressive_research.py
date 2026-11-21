import time
from fastapi.testclient import TestClient
import app as module

HEADERS={'Origin':'http://127.0.0.1:4321'}
BRIEF={'name':'Watchers','platform':'iOS','status':'unlaunched','category':'finance','description':'Alerts traders to missed chart setups while away from a screen.'}


def test_progressive_job_owner_isolation_and_completion(tmp_path,monkeypatch):
 monkeypatch.setattr(module,'DB',tmp_path/'trial.sqlite3')
 monkeypatch.setattr(module,'LIVE_SEARCH',False)
 monkeypatch.setattr(module,'STREAM_JOBS',{})
 with TestClient(module.app,headers=HEADERS) as client:
  client.post('/session');identifier=client.post('/research',json=BRIEF).json()['id']
  assert client.post(f'/projects/{identifier}/stream').status_code==200
  for _ in range(100):
   result=client.get(f'/projects/{identifier}/stream').json()
   if result['status']!='running':break
   time.sleep(.01)
  assert result['status']=='complete' and result['workspace']['project']['name']=='Watchers'
  with TestClient(module.app,headers=HEADERS) as stranger:
   stranger.post('/session')
   assert stranger.get(f'/projects/{identifier}/stream').status_code==404
   assert stranger.post(f'/projects/{identifier}/stream').status_code==404


def test_collection_tick_requires_cached_model_and_obeys_bounds(tmp_path,monkeypatch):
 import collect_public,research_retrieval
 monkeypatch.setattr(module,'DB',tmp_path/'trial.sqlite3')
 p=module.Project(**BRIEF);research_retrieval.save_model(p,{lane:['missing chart setups','tired of watching charts'] for lane in ('for_you','competitors','conversations')})
 collect_public.subscribe(p)
 calls=[]
 result=collect_public.collect_once(max_queries=1,search=lambda query,objective:calls.append(query) or '')
 assert result=={'queries':1,'collected':0,'succeeded':1,'failed':0}
 assert len(calls)==1 and 'after:' in calls[0]
 with module.connect() as db:assert db.execute("SELECT hits FROM limits WHERE key LIKE 'public-search:%'").fetchone()[0]==1


def test_reopening_persisted_workspace_does_not_start_research(tmp_path,monkeypatch):
 import json,hashlib
 monkeypatch.setattr(module,'DB',tmp_path/'trial.sqlite3')
 monkeypatch.setattr(module,'LIVE_SEARCH',False)
 monkeypatch.setattr(module,'STREAM_JOBS',{})
 with TestClient(module.app,headers=HEADERS) as client:
  client.post('/session');identifier=client.post('/research',json=BRIEF).json()['id']
  with module.connect() as db:
   row=db.execute('SELECT * FROM projects WHERE id=?',(identifier,)).fetchone()
   project=module.research_project(module.Project(**json.loads(row['data'])),{})
   key=hashlib.sha256((row['owner']+str(module.SEARCH_VERSION)+module.cache_key(project)+module.provider_cache_signature()).encode()).hexdigest()
   db.execute('INSERT OR REPLACE INTO research_cache VALUES(?,?,?)',(key,row['results'],time.time()))
  monkeypatch.setattr(module,'LIVE_SEARCH',True)
  def forbidden(*args,**kwargs):raise AssertionError('A current saved workspace must not search again')
  monkeypatch.setattr(module,'research_live',forbidden)
  for _ in range(2):
   module.STREAM_JOBS.clear() # Simulate process-local job state lost on restart.
   response=client.post(f'/projects/{identifier}/stream')
   assert response.status_code==200 and response.json()['status']=='complete'
   assert response.json()['workspace']['project']['name']==BRIEF['name']
  with TestClient(module.app,headers=HEADERS) as stranger:
   stranger.post('/session')
   assert stranger.post(f'/projects/{identifier}/stream').status_code==404
