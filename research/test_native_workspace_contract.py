"""Cross-project reuse, native-only collection and independent lane contracts."""
import json,sqlite3,time
from datetime import datetime,timezone
import pytest
from app import Project
import research_providers as providers
from research_retrieval import connect


def product():
 return Project(name='Remote',platform='iOS',status='launched',category='other',
  description='Control a smart television from a phone when the physical remote is lost.',
  keywords=['smart TV','lost remote'])


def test_fresh_query_shared_across_projects_and_stale_query_refreshes_once(tmp_path,monkeypatch):
 path=tmp_path/'jobs.sqlite3';starts=[]
 def start():starts.append(1);return {'run_id':str(len(starts))}
 _,_,observed=providers.cached_collection('public-query',path,start,max_age=100)
 with sqlite3.connect(path) as db:db.execute('UPDATE media_jobs SET rows=?',(json.dumps([{'original':'post'}]),))
 assert providers.cached_collection('public-query',path,start,max_age=100)[1]==[{'original':'post'}]
 assert starts==[1]
 monkeypatch.setattr(providers.time,'time',lambda:observed+101)
 assert providers.cached_collection('public-query',path,start,max_age=100)[0]['run_id']=='2'
 assert starts==[1,1]
 # Pending work must be polled, never restarted even if the clock advances.
 monkeypatch.setattr(providers.time,'time',lambda:observed+1000)
 providers.cached_collection('public-query',path,start,max_age=100)
 assert len(starts)==2


def test_paused_collection_reuses_expired_cache_without_start(tmp_path):
 path=tmp_path/'jobs.sqlite3'
 providers.cached_collection('query',path,lambda:{'run_id':'one'})
 with sqlite3.connect(path) as db:db.execute('UPDATE media_jobs SET rows=?,created=0',('[]',))
 assert providers.cached_collection('query',path,lambda:pytest.fail('No paid start'))[1]==[]


def test_public_corpus_does_not_copy_private_project_fields():
 s={'id':'public','platform':'TikTok','kind':'Video','url':'https://www.tiktok.com/@creator/video/1234567890',
    'title':'Smart TV remote ideas','summary':'Controlling a smart television without its original remote.',
    'owner':'customer-secret','project_id':'private-project','notes':'private note','evaluation':{'reason':'private verdict'}}
 providers.remember_public_sources([s])
 with connect() as db:record=json.loads(db.execute('SELECT data FROM public_sources').fetchone()[0])
 assert not {'owner','project_id','notes','evaluation'} & record.keys()


def test_relevant_older_niche_post_survives_more_than_two_thousand_unrelated_posts():
 now=time.time()
 target={'id':'target','platform':'TikTok','kind':'Video','url':'https://www.tiktok.com/@creator/video/1234567890',
  'title':'Lost smart TV remote','summary':'Use a phone to control your smart television.','published_at':datetime.now(timezone.utc).isoformat()}
 providers.remember_public_sources([target])
 with connect() as db:
  db.execute('UPDATE public_sources SET created=?',(now-1000,))
  db.executemany('INSERT INTO public_sources VALUES(?,?,?)',[(f'https://www.tiktok.com/@other/video/{2234567890+i}',json.dumps({**target,'id':str(i),'url':f'https://www.tiktok.com/@other/video/{2234567890+i}','title':'Baking sourdough','summary':'Bread baking recipes'}),now+i/10000) for i in range(2100)])
  # Simulate migration of a pre-existing corpus.
  db.execute('DELETE FROM public_source_search')
 found=providers.remembered_candidates(product(),cached_only=True)
 assert any(s['id']=='target' for s in found)


def test_keywords_broaden_native_discovery_without_entering_competitor_queries():
 from native_collection import queries
 p=product();model={'for_you':['television control phone'],'competitors':['smart television remote apps']}
 for network in ('TikTok','Instagram'):
  discovery=queries(p,model,'for_you',network)
  competitors=queries(p,model,'competitors',network)
  assert any('lost remote' in q for q in discovery)
  assert all('lost remote' not in q for q in competitors)
  assert not any('site:' in q or 'https://' in q for q in discovery)


def test_default_background_collection_calls_native_adapter_only(monkeypatch,tmp_path):
 import app,collect_public,native_collection
 from research_retrieval import save_model
 p=product();monkeypatch.setattr(app,'DB',tmp_path/'projects.sqlite3')
 save_model(p,{'for_you':['smart television remote tips'],'competitors':['remote control software'],'conversations':['lost television remote']})
 collect_public.subscribe(p)
 called=[]
 monkeypatch.setattr(native_collection,'collect',lambda task:called.append(task) or [])
 result=collect_public.collect_once(2,now=1000)
 assert result['succeeded']==2 and len(called)==2
 assert all('site:' not in t['query'] and 'after:' not in t['query'] for t in called)


def test_new_competitor_policy_rejects_reviews_but_keeps_first_party_posts():
 from research_quality import select_results
 p=product();now=datetime.now(timezone.utc).isoformat()
 def source(ident,text,quote):
  return {'id':ident,'url':'https://www.instagram.com/p/'+ident+'/', 'platform':'Instagram','kind':'Video',
   'title':text,'summary':text,'published_at':now,
   'evaluation':{'provider':'gemini','policy_version':15,'checked_at':now,'intent':'competitor','relevance':.8,
    'evidence_quote':text,'competitor_name':'RemoteMate','competitor_job_quote':text,'competitor_publisher_quote':quote}}
 review=source('review','I reviewed RemoteMate, a phone remote for smart televisions.','I reviewed RemoteMate')
 maker=source('maker','We built our app RemoteMate to control smart televisions from your phone.','We built our app RemoteMate')
 maker['metrics']={'views':1800,'provider':'fixture','checked_at':now}
 chosen,_=select_results(p,[review,maker],require_evaluation=True)
 assert [s['id'] for s in chosen]==['maker']


def test_third_party_demo_can_inspire_for_you_without_becoming_a_competitor():
 from research_quality import select_results
 p=product();now=datetime.now(timezone.utc).isoformat()
 text='I reviewed RemoteMate, a phone remote for smart televisions.'
 source={'id':'review','url':'https://www.instagram.com/reel/review/', 'platform':'Instagram','kind':'Video',
  'title':text,'summary':text,'author':'independent_creator','published_at':now,
  'metrics':{'views':1800,'provider':'fixture','checked_at':now},
  'evaluation':{'provider':'gemini','policy_version':15,'checked_at':now,'intent':'competitor','relevance':.8,
  'evidence_quote':text,'competitor_name':'RemoteMate','competitor_job_quote':'a phone remote for smart televisions',
  'competitor_publisher_quote':'I reviewed RemoteMate'}}
 chosen,_=select_results(p,[source],require_evaluation=True)
 assert len(chosen)==1 and chosen[0]['intent']=='discover' and not chosen[0]['competitor']
 assert chosen[0]['publisher_basis']=='third_party_demonstration'
 source['evaluation']['relevance']=.2
 assert select_results(p,[source],require_evaluation=True)[0]==[]


def test_matching_brand_account_needs_literal_brand_voice_to_enter_competitors():
 from research_quality import select_results
 p=product();now=datetime.now(timezone.utc).isoformat()
 text='RemoteMate controls smart televisions. The download link is in our profile.'
 s={'id':'brand','url':'https://www.tiktok.com/@remotemate.app/video/1234567890123/',
  'platform':'TikTok','kind':'Video','author':'remotemate.app','title':text,'summary':text,'published_at':now,
  'evidence':{'type':'original_platform_post'},
  'metrics':{'views':3500,'likes':20,'provider':'fixture','checked_at':now},
  'evaluation':{'provider':'gemini','policy_version':15,'checked_at':now,'intent':'competitor','relevance':.9,
  'evidence_quote':text,'competitor_name':'RemoteMate','competitor_job_quote':'RemoteMate controls smart televisions.',
  'competitor_publisher_quote':'The download link is in our profile.'}}
 chosen,_=select_results(p,[s],require_evaluation=True)
 assert len(chosen)==1 and chosen[0]['intent']=='competitors'
 assert chosen[0]['publisher_basis']=='matching_account_and_brand_voice'
 s['evaluation']['competitor_publisher_quote']='A made-up ownership claim'
 assert select_results(p,[s],require_evaluation=True)[0]==[]


def test_background_conversations_reuse_native_compiler_instead_of_long_index_phrases():
 from native_collection import queries
 p=product()
 model={'native_x_query_plan':['lost TV remote','remote pairing problem','TV volume control'],
        'conversations':['a very long sentence about apps and smart televisions that should not be the native query']}
 planned=queries(p,model,'conversations','X')
 assert planned[:3]==model['native_x_query_plan']
 assert model['conversations'][0] not in planned


@pytest.mark.parametrize('quote',[
 'Any tips for sticking to a journaling habit?',
 'Struggling to keep a daily journal and I need a way to remember.',
 'I wish I could record meals without all this manual food logging.',
])
def test_natural_need_wording_can_reach_evaluation_without_formal_app_requests(quote):
 from research_quality import route_source
 assert route_source({'title':quote,'summary':'','platform':'Reddit'})=='conversations'


def test_complete_checked_corpus_returns_before_credentials_or_paid_planning(monkeypatch):
 import live_discovery as live,native_access
 monkeypatch.delenv('OUTLOUD_RESEARCH_CACHE_ONLY',raising=False)
 monkeypatch.setenv('OUTLOUD_MEDIA_SEARCH_ALLOWED','1')
 monkeypatch.setattr(providers,'configuration',lambda:{'enabled':True,'evaluation':True})
 monkeypatch.setattr(providers,'search_brief',lambda *a:pytest.fail('A complete checked corpus needs no new paid plan'))
 monkeypatch.setattr(native_access,'require',lambda:pytest.fail('Serving checked originals needs no live collector token'))
 from datetime import datetime, timezone
 checked=[{'id':lane,'section':'conversations' if lane=='conversations' else 'discover','intent':lane,
           'platform':'X' if lane=='conversations' else 'TikTok','url':'https://example.test/'+lane,'published_at':datetime.now(timezone.utc).isoformat(),
           'evidence':{'type':'original_platform_post'}} for lane in ('discover','competitors','conversations')]
 monkeypatch.setattr(providers,'remembered_candidates',lambda p:checked)
 monkeypatch.setattr(providers,'cached_evaluations',lambda p,s:s)
 monkeypatch.setattr(live,'select_results',lambda *a,**k:(checked,{'launch_ready':True,'lane_counts':{'discover':1,'competitors':1,'conversations':1}}))
 monkeypatch.setattr(live,'LANE_LIMITS',{'discover':1,'competitors':1,'conversations':1})
 result=live.research_live(product())
 assert result['mode']=='collected_store'
 assert len(result['discover'])+len(result['conversations'])==3


def test_legacy_profile_can_research_without_inventing_capabilities_or_weakening_new_input():
 import app
 fields=dict(name='Legacy tool',platform='Web',status='launched',category='other',
             description='An invoice reminder tool',keywords=['invoice'],competitors=None)
 with pytest.raises(Exception):app.Project(**fields)
 p=app.project_from_record(fields)
 assert p.description=='User description: An invoice reminder tool'
 assert p.competitors==[]
 assert 'automated' not in p.description
 assert fields['description']=='An invoice reminder tool'


def test_native_research_publishes_checked_cards_while_another_collector_runs(monkeypatch):
    from threading import Event

    import competitor_accounts
    import live_discovery
    import native_access
    import research_retrieval
    import research_routing

    monkeypatch.setenv('OUTLOUD_RETRIEVAL_MODE', 'native')
    monkeypatch.setenv('OUTLOUD_RESEARCH_CACHE_ONLY', '0')
    monkeypatch.setenv('OUTLOUD_MEDIA_SEARCH_ALLOWED', '1')
    monkeypatch.setenv('OUTLOUD_CONVERSATION_START_ALLOWED', '0')
    now = datetime.now(timezone.utc).isoformat()
    quote = 'Here is how a phone replaces a lost television remote.'
    post = {
        'id': 'native-demo', 'platform': 'Instagram', 'url': 'https://www.instagram.com/reel/demo/',
        'kind': 'Video', 'title': 'Remote control demo', 'summary': quote, 'author': 'creator',
        'published_at': now, 'section': 'discover', 'competitor': False,
        'metrics': {'provider': 'apify', 'checked_at': now, 'views': 12000},
        'evidence': {'type': 'original_platform_post'},
        'media': {'poster': 'https://example.com/cover.jpg'},
    }
    verdict = {'provider': 'gemini', 'checked_at': now, 'intent': 'creative_reference',
               'relevance': .9, 'evidence_quote': quote}
    appeared = Event()
    slow_collector_finished = Event()
    snapshots = []

    def collect(phrases, limit, wait, platform, keyword):
        if platform == 'Instagram':
            return [post.copy()]
        if appeared.wait(timeout=3):
            slow_collector_finished.set()
        return []

    def publish(snapshot):
        snapshots.append(snapshot)
        if any(source['id'] == post['id'] for source in snapshot['discover']):
            appeared.set()

    monkeypatch.setattr(native_access, 'require', lambda: None)
    monkeypatch.setattr(providers, 'configuration', lambda: {'enabled': True, 'evaluation': True})
    monkeypatch.setattr(providers, 'remembered_candidates', lambda project: [])
    monkeypatch.setattr(providers, 'cached_evaluations', lambda project, sources: [])
    monkeypatch.setattr(providers, 'search_brief', lambda project: {})
    monkeypatch.setattr(providers, 'native_search_terms', lambda project: {})
    monkeypatch.setattr(research_routing, 'media_plan', lambda *args: [
        {'platform': platform, 'lane': 'discover', 'phrases': ['tv remote']}
        for platform in ('TikTok', 'Instagram')
    ])
    monkeypatch.setattr(providers, 'discover_native_media', collect)
    monkeypatch.setattr(providers, 'evaluate', lambda project, sources, **kwargs: {
        source['id']: verdict for source in sources
    })
    monkeypatch.setattr(providers, 'enrich_media', lambda sources: (sources, []))
    monkeypatch.setattr(providers, 'remember_public_sources', lambda sources: None)
    monkeypatch.setattr(research_retrieval, 'shortlist', lambda project, sources: (sources, {}))
    monkeypatch.setattr(competitor_accounts, 'collect_for_project', lambda project: ([], {}))

    result = live_discovery.research_live(product(), on_progress=publish)

    assert slow_collector_finished.is_set()
    assert any(snapshot['discover'] for snapshot in snapshots)
    assert [source['id'] for source in result['discover']] == [post['id']]
