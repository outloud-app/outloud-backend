"""Full research requires server entitlement, independent of browser/client flags."""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
import app as module
import desktop_access as access

BRIEF={'name':'Desktop app','platform':'Mac','status':'unlaunched','url':'','description':'A habit tracker for people rebuilding routines after missed days.','category':'habits','keywords':['habit','routine']}
TOKEN='a'*43
SUBJECT='b'*64

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'DB',tmp_path/'desktop.sqlite3')
    monkeypatch.setattr(module,'LIVE_SEARCH',False)
    monkeypatch.setenv('OUTLOUD_LICENSE_AUTHORITY','https://licenses.example')
    with TestClient(module.app,headers={"Origin":"http://127.0.0.1:4321"}) as client:yield client


def reply(monkeypatch,**updates):
    calls=[]
    entitlement={'status':'active','unlocked':True,'environment':'live','license_subject':SUBJECT,'access_ends_at':'2099-11-06T00:00:00+00:00',**updates}
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,json=entitlement)
    monkeypatch.setattr(access.httpx,'post',post)
    return calls


def test_desktop_flag_or_browser_cookie_does_not_unlock(client,monkeypatch):
    calls=reply(monkeypatch)
    client.post('/session')
    assert client.post('/desktop/research',headers={'X-Outloud-Desktop':'true'},json=BRIEF).status_code==401
    assert calls==[]


@pytest.mark.parametrize('updates',[
    {'status':'reserved','unlocked':False},{'status':'revoked'},{'environment':'test'},
    {'unlocked':'true'},{'access_ends_at':'2000-01-01T00:00:00+00:00'},
    {'access_ends_at':None},{'license_subject':''},
])
def test_inactive_or_untrusted_entitlements_are_denied(client,monkeypatch,updates):
    reply(monkeypatch,**updates)
    assert client.post('/desktop/research',headers={'Authorization':'Bearer '+TOKEN},json=BRIEF).status_code==403


def test_full_results_require_live_license_and_preserve_owner_isolation(client,monkeypatch):
    calls=reply(monkeypatch)
    headers={'Authorization':'Bearer '+TOKEN}
    created=client.post('/desktop/research',headers=headers,json=BRIEF)
    assert created.status_code==200
    project=created.json()['id']
    sources=[{'id':str(i),'platform':'X','kind':'Text','title':'Private reference '+str(i),'summary':'Actual matched content','author':'Author','url':'https://x.com/example/status/'+str(i),'competitor':False,'tone':'neutral'} for i in range(5)]
    with module.connect() as db:
        db.execute('UPDATE projects SET results=? WHERE id=?',(json.dumps({'discover':sources,'conversations':[],'match_version':2}),project))
    result=client.get('/desktop/projects/'+project,headers=headers)
    assert len(result.json()['results']['discover'])==5
    assert not any(s.get('locked') for s in result.json()['results']['discover'])
    assert all(call[0]=='https://licenses.example/v1/licenses/check' for call in calls)
    # Browser cannot request the private projection with a query parameter.
    client.post('/session')
    assert client.get('/projects/'+project+'?desktop=true').status_code==404
    reply(monkeypatch,license_subject='c'*64)
    assert client.get('/desktop/projects/'+project,headers=headers).status_code==404
    # A new token for the same license keeps the same project owner.
    reply(monkeypatch)
    assert client.get('/desktop/projects/'+project,headers={'Authorization':'Bearer '+'d'*43}).status_code==200


def test_native_metadata_without_browser_origin_still_requires_entitlement(client,monkeypatch):
    client.headers.pop('origin',None)
    monkeypatch.setattr(module,'page_metadata',lambda url: {'title':'Example app','description':'A product that helps people rebuild routines after missing a day.','url':url,'image':''})
    assert client.post('/desktop/metadata',json={'url':'example.com'}).status_code==403
    reply(monkeypatch,status='reserved',unlocked=False)
    assert client.post('/desktop/metadata',headers={'Authorization':'Bearer '+TOKEN},json={'url':'example.com'}).status_code==403
    reply(monkeypatch)
    result=client.post('/desktop/metadata',headers={'Authorization':'Bearer '+TOKEN},json={'url':'example.com'})
    assert result.status_code==200
    assert result.json()['title']=='Example app'
    # Native exception is not a blanket exemption for browser endpoints.
    assert client.post('/metadata',headers={'Authorization':'Bearer '+TOKEN},json={'url':'example.com'}).status_code==403


def test_native_project_create_without_origin(client,monkeypatch):
    client.headers.pop('origin',None)
    reply(monkeypatch)
    result=client.post('/desktop/research',headers={'Authorization':'Bearer '+TOKEN},json=BRIEF)
    assert result.status_code==200
    assert client.get('/desktop/projects/'+result.json()['id'],headers={'Authorization':'Bearer '+TOKEN}).status_code==200


def test_local_development_access_requires_all_boundaries(monkeypatch):
    from starlette.requests import Request
    monkeypatch.setenv('OUTLOUD_LOCAL_TESTING','1')
    monkeypatch.setenv('OUTLOUD_LOCAL_DESKTOP','1')
    def request(peer='127.0.0.1', host='127.0.0.1', origin=None):
        headers=[(b'host',host.encode()),(b'authorization',b'Bearer outloud-local-development')]
        if origin:headers.append((b'origin',origin.encode()))
        return Request({'type':'http','method':'GET','path':'/desktop/projects','headers':headers,
                        'scheme':'http','server':('127.0.0.1',8766),'client':(peer,12345),'query_string':b''})
    assert access.desktop_identity(request())=='desktop:local-development'
    assert not access.local_development_request(request(peer='203.0.113.1'))
    assert not access.local_development_request(request(host='public.example'))
    assert not access.local_development_request(request(origin='http://127.0.0.1:4321'))
    monkeypatch.delenv('OUTLOUD_LOCAL_DESKTOP')
    assert not access.local_development_request(request())
    monkeypatch.setenv('OUTLOUD_LOCAL_DESKTOP','1')
    monkeypatch.delenv('OUTLOUD_LOCAL_TESTING')
    assert not access.local_development_request(request())


@pytest.mark.parametrize('status',['launched','unlaunched'])
def test_desktop_requires_research_keywords(client,monkeypatch,status):
    reply(monkeypatch)
    payload={**BRIEF,'status':status,'keywords':[]}
    result=client.post('/desktop/research',headers={'Authorization':'Bearer '+TOKEN},json=payload)
    assert result.status_code==422


def test_keywords_have_a_hundred_character_budget_and_are_not_features():
    from pydantic import ValidationError
    from product_profile import research_context
    from research_retrieval import retrieval_queries
    p=module.Project(**{**BRIEF,'keywords':['chart，price,Chart, forex']})
    assert p.keywords==['chart','price','forex']
    assert p.features==[]
    assert research_context(p)['research_keywords']==p.keywords
    assert 'chart' in retrieval_queries(p)['discover']
    assert 'not confirmed product capabilities' in retrieval_queries(p)['conversations']
    assert module.Project(**{**BRIEF,'keywords':['a'*100]}).keywords==['a'*100]
    with pytest.raises(ValidationError):module.Project(**{**BRIEF,'keywords':['a'*101]})


def test_desktop_progress_requires_entitlement_on_every_poll(client,monkeypatch):
 import time
 reply(monkeypatch)
 headers={'Authorization':'Bearer '+TOKEN}
 project=client.post('/desktop/research',headers=headers,json=BRIEF).json()['id']
 monkeypatch.setattr(module,'STREAM_JOBS',{})
 sources=[{'id':str(i),'platform':'X','kind':'Text','title':'Matched content '+str(i),'summary':'Original complete content',
           'author':'Author','url':'https://x.com/example/status/'+str(i),'competitor':False,'tone':'neutral'} for i in range(5)]
 with module.connect() as db:
  db.execute('UPDATE projects SET results=? WHERE id=?',(json.dumps({'discover':sources,'conversations':[],'match_version':2}),project))
 assert client.post('/desktop/projects/'+project+'/stream',headers=headers,json={}).status_code==200
 for _ in range(100):
  result=client.get('/desktop/projects/'+project+'/stream',headers=headers)
  if result.json()['status']!='running':break
  time.sleep(.01)
 assert result.json()['status']=='complete',result.json()
 assert len(result.json()['workspace']['results']['discover'])==5
 assert all(not s.get('locked') for s in result.json()['workspace']['results']['discover'])
 assert client.get('/desktop/projects/'+project+'/stream').status_code==401
 reply(monkeypatch,status='revoked')
 assert client.get('/desktop/projects/'+project+'/stream',headers=headers).status_code==403
 reply(monkeypatch,license_subject='c'*64)
 assert client.get('/desktop/projects/'+project+'/stream',headers=headers).status_code==404


def test_browser_stream_query_cannot_enable_desktop_projection(client,monkeypatch):
 import time
 monkeypatch.setattr(module,'STREAM_JOBS',{})
 client.post('/session')
 project=client.post('/research',json=BRIEF).json()['id']
 sources=[{'id':str(i),'platform':'X','kind':'Text','title':'Reference '+str(i),'summary':'Original source content',
           'author':'Author','url':'https://x.com/example/status/'+str(i),'competitor':False,'tone':'neutral'} for i in range(5)]
 with module.connect() as db:db.execute('UPDATE projects SET results=? WHERE id=?',(json.dumps({'discover':sources,'conversations':[],'match_version':2}),project))
 assert client.post('/projects/'+project+'/stream?desktop=true').status_code==200
 for _ in range(100):
  result=client.get('/projects/'+project+'/stream?desktop=true').json()
  if result['status']!='running':break
  time.sleep(.01)
 assert result['status']=='complete',result
 assert any(s.get('locked') for s in result['workspace']['results']['discover'])


def test_partial_desktop_feed_has_full_content_and_revision_then_completes(client,monkeypatch):
 import threading,time
 reply(monkeypatch)
 headers={'Authorization':'Bearer '+TOKEN}
 identifier=client.post('/desktop/research',headers=headers,json=BRIEF).json()['id']
 monkeypatch.setattr(module,'STREAM_JOBS',{})
 published=threading.Event();finish=threading.Event()
 sources=[{'id':str(i),'platform':'X','kind':'Text','title':'Reference '+str(i),'summary':'Full source text',
           'author':'Author','url':'https://x.com/example/status/'+str(i),'competitor':False,'tone':'neutral'} for i in range(5)]
 workspace={'id':identifier,'results':{'discover':sources,'conversations':[]}}
 def response(project_id,request,desktop=False,on_progress=None,**kwargs):
  assert desktop is True and project_id==identifier
  on_progress({'stage':'evaluating','discover':sources,'conversations':[]})
  published.set();assert finish.wait(timeout=3)
  return workspace
 monkeypatch.setattr(module,'project_response',response)
 try:
  assert client.post('/desktop/projects/'+identifier+'/stream',headers=headers,json={}).status_code==200
  assert published.wait(timeout=2)
  partial=client.get('/desktop/projects/'+identifier+'/stream',headers=headers).json()
  assert partial['status']=='running' and partial['revision']==1
  assert len(partial['workspace']['results']['discover'])==5
  assert all(not s.get('locked') for s in partial['workspace']['results']['discover'])
 finally:finish.set()
 for _ in range(100):
  completed=client.get('/desktop/projects/'+identifier+'/stream',headers=headers).json()
  if completed['status']!='running':break
  time.sleep(.01)
 assert completed['status']=='complete' and completed['revision']==2


def test_desktop_preview_requires_entitlement_and_project_ownership(tmp_path,monkeypatch):
    import json,time
    import app,live_discovery
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app,'DB',tmp_path/'preview.sqlite3')
    calls=[]
    monkeypatch.setattr(live_discovery,'fetch_thumbnail',lambda url:calls.append(url) or 'https://images.cdninstagram.com/new.jpg')
    video_calls = []
    def fetch_video(url):
        video_calls.append(url)
        return {'thumbnail':'https://images.cdninstagram.com/new.jpg', 'video':'https://images.cdninstagram.com/clip.mp4'}
    monkeypatch.setattr(live_discovery, 'fetch_post_preview', fetch_video)
    from starlette.requests import Request
    def identity(request: Request):
        request.state.desktop_owner='desktop:test-preview'
        return 'desktop:test-preview'
    app.app.dependency_overrides[app.desktop_identity]=identity
    url='https://www.instagram.com/p/preview123/'
    try:
        with app.connect() as db:
            db.execute('INSERT INTO projects(id,owner,data,results,created) VALUES(?,?,?,?,?)',('preview-project','desktop:test-preview','{}',json.dumps({'discover':[{'url':url}],'conversations':[]}),time.time()))
            app.consume(db,'thumbnail:desktop:test-preview:'+time.strftime('%Y-%m-%d',time.gmtime()),100)
            db.execute("UPDATE limits SET hits=100 WHERE key LIKE 'thumbnail:%'")
        with TestClient(app.app,headers={"Authorization":"Bearer preview-test"}) as client:
            response=client.post('/desktop/sources/thumbnail',json={'url':url})
            assert response.status_code==200 and response.json()['thumbnail'].endswith('new.jpg')
            assert client.post('/desktop/sources/thumbnail',json={'url':'https://www.instagram.com/p/foreign123/'}).status_code==404
            assert len(calls)==1
            assert client.post('/desktop/sources/thumbnail',json={'url':'https://www.instagram.com/p/foreign123/','include_video':True}).status_code==404
            assert not video_calls
            playback = client.post('/desktop/sources/thumbnail',json={'url':url,'include_video':True})
            assert playback.status_code==200 and playback.json()['video'].endswith('clip.mp4')
            assert video_calls == [url]
    finally:app.app.dependency_overrides.clear()
