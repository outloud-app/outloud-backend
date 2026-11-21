"""Offline contract regressions. Fixtures do not establish live provider quality."""
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
from research_quality import select_results,LANE_LIMITS
from research_retrieval import retrieval_queries,shortlist,save_model
from live_discovery import fresh_query
from app import Project


def candidate(lane,index=0,days=0):
    text={'discover':'A practical routine for busy people in this niche.',
          'competitors':'We built a tool that performs this customer job.',
          'conversations':'I keep missing important tasks. Does anyone know an app to help?'}[lane]
    now=datetime.now(timezone.utc)
    return {'id':f'{lane}-{index}','url':f'https://example.org/{lane}/{index}',
            'author':f'Author {index}','platform':'TikTok' if lane=='discover' else 'Reddit',
            'kind':'Video' if lane=='discover' else 'Discussion','title':text,'summary':text,
            'published_at':(now-timedelta(days=days)).isoformat(),
            'metrics':{'provider':'fixture','checked_at':now.isoformat(),'views':1000},
            'evaluation':{'provider':'gemini','checked_at':now.isoformat(),'intent':{'discover':'creative_reference','competitors':'competitor','conversations':'audience_problem'}[lane],
                          'relevance':.7,'evidence_quote':text,'need_status':'unresolved' if lane=='conversations' else 'unclear','request_quote':text if lane=='conversations' else ''}}


def test_lanes_have_independent_capacity_instead_of_shared_fifteen():
    project=SimpleNamespace(problem='Avoid missing important tasks.',description='A task organizer.')
    sources=[candidate(lane,i) for lane in LANE_LIMITS for i in range(35)]
    selected,report=select_results(project,sources,require_evaluation=True)
    assert report['lane_counts']==LANE_LIMITS
    assert len(selected)==60
    assert len({s['url'] for s in selected})==60
    # Returned sources must be real inputs; targets cannot manufacture filler.
    small,_=select_results(project,[candidate('discover')],require_evaluation=True)
    assert len(small)==1


def test_recent_need_is_prioritized_and_old_creative_remains_eligible():
    project=SimpleNamespace(problem='Avoid missing important tasks.',description='A task organizer.')
    selected,_=select_results(project,[candidate('conversations',0,28),candidate('conversations',1,2),candidate('discover',2,240),candidate('conversations',3,31)],require_evaluation=True)
    assert [s['id'] for s in selected if s['intent']=='conversations']==['conversations-1','conversations-0']
    assert any(s['id']=='discover-2' for s in selected)


def test_lane_search_windows_do_not_discard_established_creatives():
    today=datetime.now(timezone.utc)
    assert fresh_query('TikTok','query').endswith((today-timedelta(days=365)).date().isoformat())
    assert fresh_query('Reddit','query',lane='competitors').endswith((today-timedelta(days=365)).date().isoformat())
    assert fresh_query('Reddit','query',lane='conversations').endswith((today-timedelta(days=30)).date().isoformat())


def test_retrieval_uses_distinct_topic_and_need_queries(monkeypatch):
    import research_retrieval
    p=Project(name='Practice',description='Plan piano practice between lessons.',audience='Piano learners',problem='Forgetting lesson assignments',platform='Web',status='unlaunched',category='other',competitors=['Practice Buddy'])
    save_model(p,{'adjacent_topics':['piano warm-ups','music learning']})
    queries=retrieval_queries(p)
    assert 'piano warm-ups' in queries['discover']
    assert 'Practice Buddy' in queries['competitors']
    assert 'Forgetting lesson assignments' in queries['conversations']
    captured=[]
    def vectors(texts,task):
        if task=='RETRIEVAL_QUERY':captured.extend(texts)
        return [[1.,0.] for _ in texts]
    monkeypatch.setattr(research_retrieval,'embed',vectors)
    shortlist(p,[candidate(lane) for lane in LANE_LIMITS])
    assert set(captured)==set(queries.values())


@pytest.mark.parametrize('limit',[0,101,True,2.5])
def test_shortlist_cannot_bypass_evaluation_batch_bound(limit):
    with pytest.raises(ValueError):shortlist(None,[],limit=limit)


def test_cached_creative_reaches_semantic_evaluation_without_exact_problem_words(monkeypatch):
    import research_providers
    from live_discovery import revalidate_candidates
    p=Project(name='Practice',description='Remember piano lesson assignments.',platform='Web',status='unlaunched',category='other')
    source={'id':'warmup','title':'Five piano warm-ups before a lesson','summary':'A music learner demonstrates a daily routine.',
            'url':'https://www.tiktok.com/@music/video/1234567890123456789','platform':'TikTok','kind':'Video'}
    monkeypatch.setattr(research_providers,'configuration',lambda:{'enabled':True,'evaluation':True})
    candidates=revalidate_candidates(p,[source])
    assert len(candidates)==1
    assert 'evaluation' not in candidates[0]  # Retained for inspection, not approved.
