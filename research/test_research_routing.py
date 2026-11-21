"""Native acquisition contracts, exercised with offline provider doubles."""
import pytest
from research_routing import mode,media_plan


def test_indexed_search_requires_explicit_mode(monkeypatch):
    monkeypatch.delenv('OUTLOUD_RETRIEVAL_MODE',raising=False)
    assert mode()=='native'
    monkeypatch.setenv('OUTLOUD_RETRIEVAL_MODE','indexed')
    assert mode()=='indexed'
    monkeypatch.setenv('OUTLOUD_RETRIEVAL_MODE','typo')
    with pytest.raises(ValueError):mode()


def test_inspiration_and_competitor_searches_are_separate():
    plan=media_plan({'tiktok':['meal prep calorie tracking','food photo calorie tracker apps']})
    assert len(plan)==4
    assert {p['platform'] for p in plan}=={'Instagram','TikTok'}
    assert all(p['phrases']==['meal prep calorie tracking'] for p in plan if p['lane']=='discover')
    assert all(p['phrases']==['food photo calorie tracker apps'] for p in plan if p['lane']=='competitors')


def test_native_request_never_launches_indexed_search(monkeypatch):
    import live_discovery as live
    import research_providers as providers
    import research_retrieval as retrieval
    import native_conversations as conversations
    from test_live_discovery import BRIEF,post
    from app import Project
    project=Project(**BRIEF)
    indexed=live.parse_results(post(),project)[0]
    item={**indexed,'evidence':{'type':'original_platform_post','provider':'apify'}}
    monkeypatch.setenv('OUTLOUD_RETRIEVAL_MODE','native')
    monkeypatch.setenv('OUTLOUD_MEDIA_SEARCH_ALLOWED','1')
    monkeypatch.setenv('OUTLOUD_CONVERSATION_START_ALLOWED','1')
    def forbidden(*a):pytest.fail('Native research must not launch web-index queries')
    monkeypatch.setattr(live,'call_search',forbidden)
    monkeypatch.setattr(providers,'configuration',lambda:{'enabled':True,'evaluation':True,'media':True})
    def unavailable_plan(project): raise ValueError('Unsupported indexed planning response')
    monkeypatch.setattr(providers,'search_brief',unavailable_plan)
    monkeypatch.setattr(providers,'remembered_candidates',lambda *a,**k:[indexed])
    monkeypatch.setattr(providers,'native_search_terms',lambda p:{'tiktok':['chart watching routines','chart alert software']})
    calls=[]
    monkeypatch.setattr(providers,'discover_native_media',lambda phrases,limit,wait,platform,keyword:calls.append((platform,phrases)) or [])
    monkeypatch.setattr(conversations,'queries_for',lambda p,platform:['task query','friction query','adjacent query'])
    monkeypatch.setattr(conversations,'discover',lambda query,limit,wait,platform:[item] if platform=='Reddit' and query=='task query' else [])
    monkeypatch.setattr(retrieval,'shortlist',lambda p,s:(s,{'mode':'offline'}))
    monkeypatch.setattr(providers,'enrich_media',lambda s:(s,[]))
    monkeypatch.setattr(providers,'evaluate',lambda p,s:{i['id']:{'provider':'gemini','intent':'audience_problem','checked_at':'2026-11-08T00:00:00Z','relevance':.99,'evidence_quote':i['summary'],'request_quote':i['summary'],'need_status':'unresolved'} for i in s})
    result=live.research_live(project,search=forbidden)
    assert len(calls)==4
    assert result['quality_report']['retrieval']['indexed_queries']==0
    assert result['mode']=='native_search'
    assert result['planning_mode']=='native_product_brief'
    assert len(result['conversations'])==1
    collections=result['quality_report']['retrieval']['native_collections']
    assert len(collections)==10
    assert sum(run.get("phase")=="fill" for run in collections)==4
    assert sum(run['returned'] for run in collections)==1
    assert all(run['status']=='completed' for run in collections)
    assert set(result['coverage'])=={'TikTok','Instagram','Reddit','X'}


def test_cache_namespace_separates_native_and_indexed(monkeypatch):
    from live_discovery import provider_cache_signature
    monkeypatch.setenv('OUTLOUD_RETRIEVAL_MODE','native');native=provider_cache_signature()
    monkeypatch.setenv('OUTLOUD_RETRIEVAL_MODE','indexed')
    assert provider_cache_signature()!=native
