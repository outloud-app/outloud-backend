import json
import pytest
from fastapi.testclient import TestClient
import app as module
from live_discovery import parse_results, post_identity, research_live, cache_key, ResearchUnavailable

BRIEF={'name':'Watchers','platform':'iOS','status':'unlaunched','url':'','description':'A forex and cryptocurrency trading scanner for chart patterns and market alerts.','category':'finance','audience':'Forex and crypto traders','problem':'Missing chart setups while away from a screen','features':['Technical chart pattern alerts','Cryptocurrency market scanner']}

def test_tiktok_thumbnail_metadata_uses_www_original(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    import live_discovery
    requests=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_bytes(self):yield b'{"thumbnail_url":"https://p16.tiktokcdn.com/post.jpg"}'
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream(self,method,url):
            requests.append(url)
            return Response()
    monkeypatch.setattr(live_discovery.httpx,'Client',Client)
    assert live_discovery.fetch_thumbnail('https://tiktok.com/@trader/video/123456')=='https://p16.tiktokcdn.com/post.jpg'
    assert parse_qs(urlsplit(requests[0]).query)['url']==['https://www.tiktok.com/@trader/video/123456/']

def post(platform='Reddit', title='Forex chart pattern scanners',url=None):
    urls={'Reddit':'https://www.reddit.com/r/Forex/comments/abc123/chart_scanners/','X':'https://x.com/trader/status/123456','Instagram':'https://www.instagram.com/p/AbCd123/','TikTok':'https://www.tiktok.com/@trader/video/123456'}
    return f'Title: {title}\nURL: {url or urls[platform]}\nPublished: 2026-11-01T00:00:00Z\nAuthor: Trader\nHighlights:\nI keep missing forex chart patterns and need a scanner with market alerts while away from charts.'

@pytest.mark.parametrize('url',['http://reddit.com/r/a/comments/b/c','https://evil.com/r/a/comments/b/c','https://reddit.com.evil.com/r/a/comments/b/c','https://user:pass@reddit.com/r/a/comments/b/c','https://reddit.com/search?q=forex','https://instagram.com/trader','https://x.com/search?q=scanner'])
def test_only_original_public_post_urls_are_accepted(url):
    assert post_identity(url) is None

def test_actual_excerpt_is_preserved_and_unknown_metrics_not_fabricated():
    source=parse_results(post(),module.Project(**BRIEF))[0]
    assert source['platform']=='Reddit'
    assert source['evidence']['engagement_verified'] is False
    assert 'views' not in source and 'likes' not in source
    assert source['summary'].startswith('I keep missing forex')

def test_cross_platform_results_do_not_pollute_the_requested_platform():
    result=research_live(module.Project(**BRIEF),search=lambda q,o:post())
    assert len(result['conversations'])==1
    assert result['coverage']['TikTok']==0
    assert result['mode']=='live_search'

def test_research_includes_platform_mix_and_deduplicates_with_ten_maximum():
    def search(query,objective):
        platform=next(p for p in ['Reddit','Instagram','TikTok'] if p.lower() in query.lower()) if 'site:x.com' not in query else 'X'
        return post(platform)+'\n---\n'+post(platform)
    result=research_live(module.Project(**BRIEF),search=search)
    assert sum(result['coverage'].values())==4
    assert len(result['discover'])==2 and len(result['conversations'])==2

def test_no_results_never_fall_back_to_unrelated_stored_content():
    with pytest.raises(ResearchUnavailable):research_live(module.Project(**BRIEF),search=lambda q,o:'')

def test_each_project_context_has_its_own_cache_key():
    a=module.Project(**BRIEF)
    b=module.Project(**{**BRIEF,'audience':'Long-term equity investors'})
    assert cache_key(a)!=cache_key(b)

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'DB',tmp_path/'research.sqlite3')
    monkeypatch.setattr(module,'LIVE_SEARCH',True)
    with TestClient(module.app,headers={'Origin':'http://127.0.0.1:4321'}) as client:
        client.post('/session');yield client

def test_reopening_uses_project_specific_live_cache_without_spending_again(client,monkeypatch):
    calls=[]
    def search(project):
        calls.append(project.name)
        return research_live(project,search=lambda q,o:post())
    monkeypatch.setattr(module,'research_live',search)
    id=client.post('/research',json=BRIEF).json()['id']
    assert client.get('/projects/'+id).json()['results']['mode']=='live_search'
    assert client.get('/projects/'+id).status_code==200
    assert calls==['Watchers']
    with module.connect() as db:
        assert db.execute("SELECT hits FROM limits WHERE key LIKE 'public-search:%'").fetchone()[0]==4

def test_search_failure_preserves_project_and_can_retry(client,monkeypatch):
    def fail(project):raise ResearchUnavailable('Search is busy. Retry.')
    monkeypatch.setattr(module,'research_live',fail)
    id=client.post('/research',json=BRIEF).json()['id']
    assert client.get('/projects/'+id).status_code==503
    assert any(p['id']==id for p in client.get('/projects').json())


def test_expired_current_version_keeps_candidates_for_fresh_evaluation(client,monkeypatch):
    import time
    original=module.research_live
    result=original(module.Project(**BRIEF),search=lambda q,o:post())
    monkeypatch.setattr(module,'provider_cache_signature',lambda:':configured-test')
    monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','1')
    calls=[]
    def search(project,prior_candidates,before_search=None):
        calls.append(prior_candidates)
        return result
    monkeypatch.setattr(module,'research_live',search)
    project_id=client.post('/research',json=BRIEF).json()['id']
    assert client.get('/projects/'+project_id).status_code==200
    with module.connect() as db:
        db.execute('UPDATE research_cache SET created=?',(time.time()-22000,))
    assert client.get('/projects/'+project_id).status_code==200
    assert calls[0]==[]
    assert any(source['url']==result['conversations'][0]['url'] for source in calls[1])


def test_reopening_does_not_erase_provider_coverage_blockers(client,monkeypatch):
    import research_quality
    result=research_live(module.Project(**BRIEF),search=lambda q,o:post())
    result['research_issues']=['Instagram: collection is incomplete.']
    monkeypatch.setattr(module,'research_live',lambda project:result)
    monkeypatch.setattr(research_quality,'select_results',lambda project,candidates,**kwargs:(candidates,{'launch_ready':True,'blockers':[]}))
    project_id=client.post('/research',json=BRIEF).json()['id']
    for _ in range(2):
        response=client.get('/projects/'+project_id)
        assert response.status_code==200
        assert 'research_issues' not in response.json()['results']
        with module.connect() as db:
            stored=json.loads(db.execute('SELECT results FROM projects WHERE id=?',(project_id,)).fetchone()['results'])
        assert stored['quality_report']['launch_ready'] is False
        assert stored['quality_report']['blockers']==result['research_issues']


def test_excerpt_separates_title_and_index_metadata_from_body():
    from live_discovery import plain_excerpt
    title='Looking for a market scanner'
    raw=title+'\nPosted by **u/trader** in r/Trading · 11 points · 43 comments · January 10, 2026 at 4:25 AM UTC\n\nI keep missing setups while away from my charts.\n\n...\n\n**u/another** · 1 point\n> a reply'
    assert plain_excerpt(raw,title)=='I keep missing setups while away from my charts.'


def test_old_discussions_are_not_returned_as_current_opportunities():
    raw=post().replace('2026-11-01T00:00:00Z','2019-06-21T00:00:00Z')
    assert parse_results(raw,module.Project(**BRIEF))==[]


def test_broad_category_overlap_does_not_qualify_generic_tutorial():
    raw=post('TikTok',title='Technical analysis masterclass for forex traders').replace('I keep missing forex chart patterns and need a scanner with market alerts while away from charts.','Learn technical analysis, forex trading and crypto market liquidity. Indicators and trading strategies for beginners.')
    assert parse_results(raw,module.Project(**BRIEF))==[]


def test_real_social_players_are_derived_from_original_permalink():
    source=parse_results(post('TikTok'),module.Project(**BRIEF))[0]
    assert source['preview']=={'provider':'tiktok','id':'123456'}
    assert 'media' not in source  # An HTML page is not a downloadable video file.


def test_missing_author_is_derived_from_source_not_na():
    source=parse_results(post('TikTok').replace('Author: Trader','Author: N/A'),module.Project(**BRIEF))[0]
    assert source['author']=='@trader'


def test_thumbnail_only_for_a_reference_in_visitors_project(client,monkeypatch):
    import live_discovery
    monkeypatch.setattr(module,'research_live',lambda project:research_live(project,search=lambda q,o:post('Instagram')))
    monkeypatch.setattr(live_discovery,'fetch_thumbnail',lambda url:'https://images.cdninstagram.com/post.jpg')
    id=client.post('/research',json=BRIEF).json()['id']
    result=client.get('/projects/'+id).json()['results']['discover'][0]
    response=client.get('/sources/thumbnail',params={'url':result['url']})
    assert response.json()['thumbnail']=='https://images.cdninstagram.com/post.jpg'
    assert client.get('/sources/thumbnail',params={'url':'https://instagram.com/p/NotReturned/'}).status_code==404
    assert client.get('/sources/thumbnail',params={'url':'https://127.0.0.1/secret'}).status_code==400


def test_thumbnail_requests_reuse_cached_metadata(client,monkeypatch):
    import live_discovery
    calls=[]
    monkeypatch.setattr(module,'research_live',lambda project:research_live(project,search=lambda q,o:post('Instagram')))
    def thumb(url):calls.append(url);return ''
    monkeypatch.setattr(live_discovery,'fetch_thumbnail',thumb)
    id=client.post('/research',json=BRIEF).json()['id']
    url=client.get('/projects/'+id).json()['results']['discover'][0]['url']
    for _ in range(2):assert client.get('/sources/thumbnail',params={'url':url}).json()=={'thumbnail':''}
    assert len(calls)==1


def test_missing_publication_date_does_not_crash_or_claim_recency():
 from live_discovery import publication,revalidate_candidates
 assert publication(None)==(None,None)
 item=parse_results(post().replace('Published: 2026-11-01T00:00:00Z\n',''),module.Project(**BRIEF))[0]
 assert item['published_at'] is None
 assert revalidate_candidates(module.Project(**BRIEF),[item])[0]['published_at'] is None


def test_notification_request_matches_alert_problem():
 from live_discovery import revalidate_candidates
 project=module.Project(**{**BRIEF,'problem':'Traders miss setups while monitoring charts; sends alerts.'})
 item={'id':'request','title':'Service that scans the market for patterns','summary':'Looking for any service that sends me a notification when patterns have formed.','url':'https://reddit.com/r/Trading/comments/abc/scanner/','platform':'Reddit','kind':'Discussion'}
 assert revalidate_candidates(project,[item])


def test_inline_reddit_metadata_is_removed():
 from live_discovery import plain_excerpt
 text='Posted by u/name in r/Trading · 11 points · 43 comments · January 10, 2026 at 4:25 AM UTC Looking for a chart scanner.'
 assert plain_excerpt(text)=='Looking for a chart scanner.'


def test_provider_configuration_has_separate_cache_namespace(monkeypatch):
 from live_discovery import provider_cache_signature
 monkeypatch.delenv('OUTLOUD_PAID_RESEARCH',raising=False)
 assert provider_cache_signature()==':retrieval=native'
 monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','1');monkeypatch.delenv('GEMINI_API_KEY',raising=False);monkeypatch.delenv('APIFY_TOKEN',raising=False)
 first=provider_cache_signature()
 monkeypatch.setenv('GEMINI_API_KEY','placeholder')
 assert provider_cache_signature()!=first
 assert 'placeholder' not in provider_cache_signature()


def test_historical_request_is_evaluated_before_selection(monkeypatch):
    import research_providers as providers
    project=module.Project(**BRIEF)
    historic=parse_results(post(),project)[0]
    monkeypatch.setattr(providers,'configuration',lambda:{'enabled':True,'evaluation':True,'media':False})
    monkeypatch.setattr(providers,'search_brief',lambda project:{lane:['a market scanner for missing setups','alerts for chart patterns while away'] for lane in ('for_you','competitors','conversations')})
    monkeypatch.setattr(providers,'enrich_media',lambda sources:(sources,[]))
    inspected=[]
    def evaluate(project,sources):
        inspected.extend(sources)
        return {source['id']:{'provider':'gemini','checked_at':'2026-11-06','intent':'audience_problem','relevance':.98,
            'evidence_quote':source['summary'],'need_status':'unresolved','request_quote':source['summary'],
            'reason':'An unresolved request for alerts while away from charts.'} for source in sources}
    monkeypatch.setattr(providers,'evaluate',evaluate)
    result=research_live(project,search=lambda q,o:'',prior_candidates=[historic])
    assert inspected[0]['url']==historic['url']
    assert len(result['conversations'])==1
    assert result['conversations'][0]['semantic_verified'] is True


def test_other_brief_historical_candidates_are_not_reused(client,monkeypatch):
    import hashlib
    unrelated=module.Project(**{**BRIEF,'problem':'Organizing photography albums'})
    def search(project):return research_live(project,search=lambda q,o:post())
    monkeypatch.setattr(module,'research_live',search)
    id=client.post('/research',json=BRIEF).json()['id']
    with module.connect() as db:
        owner=db.execute('SELECT owner FROM projects WHERE id=?',(id,)).fetchone()[0]
        key=hashlib.sha256((owner+'2'+cache_key(unrelated)).encode()).hexdigest()
        db.execute('INSERT INTO research_cache VALUES(?,?,?)',(key,json.dumps({'discover':[], 'conversations':[{'url':'https://reddit.com/r/photos/comments/xyz/photos/'}]}),0))
    result=client.get('/projects/'+id)
    assert result.status_code==200
    assert all('photos' not in s['url'] for s in result.json()['results']['conversations'])


def test_index_cannot_overwrite_collected_original_caption():
 from live_discovery import merge_candidates
 original={'id':'one','url':'https://tiktok.com/@person/video/123/','summary':'Original caption','metrics':{'views':30000},'media':{'poster':'actual'},'evidence':{'type':'original_platform_post','engagement_verified':True}}
 indexed={**original,'summary':'Different search snippet','metrics':{},'media':{},'evidence':{'type':'indexed_public_post'}}
 assert merge_candidates([original,indexed])[0]['summary']=='Original caption'
 assert merge_candidates([indexed,original])[0]['metrics']['views']==30000


def test_query_planner_outage_leaves_project_retryable_without_generic_matches(monkeypatch,tmp_path):
 import research_providers as providers
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'empty.sqlite3'))
 monkeypatch.setattr(providers,'configuration',lambda:{'enabled':True,'evaluation':True,'media':False})
 def unavailable(project):raise RuntimeError('Planner unavailable')
 monkeypatch.setattr(providers,'search_brief',unavailable)
 searched=[]
 with pytest.raises(__import__('live_discovery').ResearchUnavailable,match='Your project is saved'):
  research_live(module.Project(**BRIEF),search=lambda q,o:searched.append(q) or post())
 assert searched==[]


def test_candidate_budget_does_not_let_promotions_crowd_out_needs_or_measured_media():
 from live_discovery import balanced_candidates
 p=module.Project(**BRIEF)
 promotions=[{'id':str(i),'url':f'https://reddit.com/r/trading/comments/{i}/post/','platform':'Reddit','title':'I built my chart pattern scanner with market alerts','summary':'Our app monitors chart setups automatically.'} for i in range(20)]
 need={'id':'need','url':'https://reddit.com/r/trading/comments/need/post/','platform':'Reddit','title':'Looking for chart setup alerts','summary':'I keep missing chart setups while away.'}
 videos=[{'id':'v'+str(i),'url':f'https://tiktok.com/@person/video/{i}/','platform':'TikTok','title':'Watching charts','summary':'Spending all day watching charts.'} for i in range(20)]
 measured={**videos[0],'id':'measured','url':'https://tiktok.com/@person/video/999/','metrics':{'provider':'apify','checked_at':'2026-11-06','views':400000}}
 selected=balanced_candidates(p,promotions+[need]+videos+[measured])
 assert need in selected and measured in selected
 assert len(selected)==24
 assert sum(s['platform']=='Reddit' for s in selected)==12
 assert sum(s['platform']=='TikTok' for s in selected)==12


def test_reddit_vote_score_comes_from_explicit_post_metadata_only():
    from live_discovery import reddit_metadata_metrics
    raw='Posted by u/trader in r/Trading 1,243 points 43 comments November 6, 2026 at 4:25 a.m. UTC\nI keep missing setups.'
    result=reddit_metadata_metrics(raw)
    assert result['score']==1243 and result['comments']==43
    assert result['provider']=='exa_index_metadata'
    assert reddit_metadata_metrics('I earned 1,243 points. My post got 43 comments.') is None
    assert reddit_metadata_metrics('Posted by u/trader in r/Trading -2 points 0 comments November 6, 2026 UTC')['score']==-2


def test_fresh_shortlist_cannot_erase_current_checked_corpus_match(monkeypatch):
    import research_providers as providers
    import research_retrieval as retrieval
    project=module.Project(**BRIEF)
    source=parse_results(post(),project)[0]
    source['evaluation']={'provider':'gemini','checked_at':'2026-11-06','intent':'audience_problem',
        'relevance':.98,'evidence_quote':source['summary'],'need_status':'unresolved',
        'request_quote':source['summary'],'reason':'Requests chart pattern alerts while away.'}
    monkeypatch.setattr(providers,'configuration',lambda:{'enabled':True,'evaluation':True,'media':False})
    monkeypatch.setattr(providers,'search_brief',lambda p:{lane:['alerts while away from charts']*6 for lane in ('for_you','competitors','conversations')})
    monkeypatch.setattr(providers,'remembered_candidates',lambda p:[source])
    monkeypatch.setattr(providers,'cached_evaluations',lambda p,s:[source])
    monkeypatch.setattr(providers,'remember_public_sources',lambda s:None)
    monkeypatch.setattr(retrieval,'shortlist',lambda p,s:([],{'mode':'test-crowded-shortlist'}))
    monkeypatch.setattr(providers,'evaluate',lambda p,s:{})
    monkeypatch.setattr(providers,'enrich_media',lambda s:(s,[]))
    result=research_live(project,search=lambda q,o:'')
    assert [s['url'] for s in result['conversations']]==[source['url']]


@pytest.mark.parametrize('page_id,status,expected,unavailable',[
    ('123456','','https://p16.tiktokcdn.com/fresh.jpg',False),
    ('987654','','',False),
    ('123456','cross_border_violation','',True),
    ('123456','content_classification,status_reviewing','',True),
    ('123456','temporary_error','',False),
])
def test_tiktok_refresh_reads_the_requested_post_cover_when_oembed_omits_it(monkeypatch,page_id,status,expected,unavailable):
    import live_discovery
    post = {'id':page_id,'video':{
        'cover':'https://tiktokcdn.com.evil.example/untrusted.jpg',
        'originCover':'https://p16.tiktokcdn.com/fresh.jpg'}}
    detail = {'statusCode':10204,'statusMsg':status} if status else {'statusCode':0,'itemInfo':{'itemStruct':post}}
    payload = {'__DEFAULT_SCOPE__':{'webapp.video-detail':detail}}
    html = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'+json.dumps(payload)+'</script>'

    class Response:
        status_code = 200
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_bytes(self): yield self.body.encode()

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def stream(self, method, url):
            return Response('{"version":"1.0"}' if '/oembed?' in url else html)

    monkeypatch.setattr(live_discovery.httpx,'Client',Client)
    result = live_discovery.fetch_post_preview('https://tiktok.com/@trader/video/123456')
    assert result['thumbnail'] == expected
    assert result.get('unavailable', False) is unavailable
