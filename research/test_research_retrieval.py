from datetime import datetime,timezone,timedelta
import json,time
from app import Project
import research_retrieval as store
from research_providers import remember_public_sources


def project(**updates):
 return Project(**{'name':'Watchers','platform':'iOS','status':'unlaunched','category':'finance','description':'Alert traders about missed chart setups without watching screens all day.',**updates})


def source(i=0,**updates):
 return {'id':str(i),'url':f'https://reddit.com/r/Trading/comments/post{i}/example/','platform':'Reddit','kind':'Discussion','author':'r/Trading','title':'How do I avoid missing chart setups?', 'summary':'I need alerts when away from my charts. Does anyone know a solution?', 'published_at':datetime.now(timezone.utc).isoformat(),**updates}


def test_problem_model_bound_to_whole_brief():
 p=project();store.save_model(p,{'conversations':['missing setups']})
 assert store.cached_model(p)=={'conversations':['missing setups']}
 assert store.cached_model(project(description='A different app for tracking baby feeding routines.')) is None


def test_ingestion_preserves_measured_media_and_observation_time():
 item=source(metrics={'provider':'apify','checked_at':'2026-11-06T00:00:00+00:00','views':100},media={'poster':'https://example.com/poster'})
 remember_public_sources([item]);remember_public_sources([source()])
 with store.connect() as db:
  record=json.loads(db.execute('SELECT data FROM public_sources').fetchone()[0])
  assert record['metrics']['views']==100 and record['media']['poster']
  assert db.execute('SELECT count(*) FROM engagement_observations').fetchone()[0]==1


def test_relative_baseline_not_invented_and_uses_same_community():
 current=source(99,metrics={'views':300,'provider':'apify','checked_at':'2026-11-06T00:00:00+00:00'})
 assert store.relative_attention(current)['status']=='insufficient_baseline'
 peers=[source(i,metrics={'views':100,'provider':'apify','checked_at':'2026-11-06T00:00:00+00:00'}) for i in range(10)]
 remember_public_sources(peers)
 result=store.relative_attention(current)
 assert result['ratio']==3 and result['sample_size']==10
 current['url']='https://reddit.com/r/Unrelated/comments/post99/example/'
 assert store.relative_attention(current)['status']=='insufficient_baseline'


def test_growth_requires_real_separated_observations():
 item=source(metrics={'views':100,'provider':'apify','checked_at':'2026-11-06T00:00:00+00:00'})
 store.observe([item]);store.observe([item])
 assert 'views_per_hour' not in store.relative_attention(item)
 item['metrics'].update(views=160,checked_at='2026-11-06T02:00:00+00:00');store.observe([item])
 assert store.relative_attention(item)['views_per_hour']==30


def test_shortlist_filters_old_before_embeddings_and_never_promotes_unverified(monkeypatch):
 captured=[]
 def embeddings(texts,task):
  captured.extend(texts)
  return [[1.,0.] for _ in texts]
 monkeypatch.setattr(store,'embed',embeddings)
 old=source(1,published_at=(datetime.now(timezone.utc)-timedelta(days=90)).isoformat())
 selected,report=store.shortlist(project(),[source(),old])
 assert len(selected)==1 and report['mode']=='embeddings'
 assert len(captured)==2
 assert 'evaluation' not in selected[0]


def test_old_measured_help_requests_do_not_consume_embedding_budget(monkeypatch):
 captured=[]
 monkeypatch.setattr(store,'embed',lambda texts,task:captured.extend(texts) or [[1.,0.] for _ in texts])
 old=source(1,published_at=(datetime.now(timezone.utc)-timedelta(days=90)).isoformat(),metrics={'provider':'apify','checked_at':datetime.now(timezone.utc).isoformat(),'score':300})
 competitor=source(2,title='I built a scanner app',summary='Our app alerts users to chart setups.',published_at=old['published_at'])
 selected,_=store.shortlist(project(),[source(),old,competitor])
 assert {s['id'] for s in selected}=={'0','2'}
 assert old['summary'] not in captured


def test_shortlist_keeps_media_platform_diversity_when_one_platform_floods_lane(monkeypatch):
 monkeypatch.setattr(store,'embed',lambda texts,task:[[1.,0.] for _ in texts])
 candidates=[source(i,platform='Instagram',kind='Image',url=f'https://www.instagram.com/p/ig{i}/',title='Tracking meals every day',summary='A customer meal tracking routine.') for i in range(40)]
 candidates.extend(source(100+i,platform='TikTok',kind='Video',url=f'https://www.tiktok.com/@creator/video/{1234567890+i}',title='Tracking meals every day',summary='A customer meal tracking routine.') for i in range(8))
 chosen,_=store.shortlist(project(),candidates,limit=15)
 assert any(s['platform']=='TikTok' for s in chosen[:5])
 assert any(s['platform']=='Instagram' for s in chosen[:5])


def test_embeddings_are_reused_and_task_specific(monkeypatch):
 import research_providers,httpx
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 monkeypatch.setattr(research_providers,'authorize',lambda *args:None)
 calls=[]
 def response(*args,**kwargs):
  calls.append(kwargs['json'])
  return httpx.Response(200,request=httpx.Request('POST','https://example.com'),json={'embeddings':[{'values':[1.]*768} for _ in kwargs['json']['requests']]})
 monkeypatch.setattr(httpx,'post',response)
 store.embed(['actual text'],'RETRIEVAL_DOCUMENT');store.embed(['actual text'],'RETRIEVAL_DOCUMENT');store.embed(['actual text'],'RETRIEVAL_QUERY')
 assert len(calls)==2


def test_relative_growth_compares_real_observations_in_same_community():
 peers=[source(i,metrics={'views':100,'provider':'fixture','checked_at':'2026-11-06T00:00:00+00:00'}) for i in range(5)]
 current=source(99,metrics={'views':100,'provider':'fixture','checked_at':'2026-11-06T00:00:00+00:00'})
 remember_public_sources(peers+[current])
 for peer in peers:peer['metrics'].update(views=120,checked_at='2026-11-06T02:00:00+00:00')
 current['metrics'].update(views=160,checked_at='2026-11-06T02:00:00+00:00')
 remember_public_sources(peers+[current])
 result=store.relative_attention(current)
 assert result['views_per_hour']==30 and result['growth_ratio']==3 and result['growth_sample_size']==5


def test_undated_peer_does_not_crash_relative_attention():
 current=source(99,metrics={'views':300,'provider':'apify','checked_at':'2026-11-07T00:00:00+00:00'})
 remember_public_sources([source(1,published_at=None,metrics={'views':100,'provider':'apify','checked_at':'2026-11-07T00:00:00+00:00'})])
 assert store.relative_attention(current)['status']=='insufficient_baseline'


def test_instagram_play_baseline_does_not_mix_plays_with_views():
 current=source(99,platform='Instagram',author='creator',url='https://www.instagram.com/reel/current/',kind='Video',metrics={'plays':300,'provider':'apify','checked_at':'2026-11-07T00:00:00+00:00'})
 peers=[source(i,platform='Instagram',author='creator',url=f'https://www.instagram.com/reel/peer{i}/',kind='Video',metrics={'plays':100,'provider':'apify','checked_at':'2026-11-07T00:00:00+00:00'}) for i in range(10)]
 remember_public_sources(peers)
 result=store.relative_attention(current)
 assert result['metric']=='plays' and result['ratio']==3 and result['sample_size']==10
 current['metrics']={'views':300,'provider':'apify','checked_at':'2026-11-07T00:00:00+00:00'}
 assert store.relative_attention(current)['status']=='insufficient_baseline'


def test_search_cannot_rejuvenate_an_original_platform_post():
 old=source(1,published_at='2023-11-27T20:05:14+00:00',summary='Original author caption',evidence={'type':'original_platform_post','provider':'apify'})
 remember_public_sources([old])
 remember_public_sources([source(1,summary='An indexed excerpt with a newly indexed date and a longer unrelated wrapper.',evidence={'type':'indexed_public_post'})])
 with store.connect() as db:record=json.loads(db.execute('SELECT data FROM public_sources').fetchone()[0])
 assert record['published_at']==old['published_at']
 assert record['summary']==old['summary']


def test_original_feed_body_replaces_longer_search_wrapper():
 remember_public_sources([source(1,summary='A long search wrapper that repeats the post title and includes author and other metadata.')])
 remember_public_sources([source(1,summary='The actual original post body.',evidence={'type':'original_platform_post','provider':'reddit_public_feed'})])
 with store.connect() as db:record=json.loads(db.execute('SELECT data FROM public_sources').fetchone()[0])
 assert record['summary']=='The actual original post body.'
