import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import Project, research_lock, RESEARCH_LOCKS
from product_profile import research_project, grounded_understanding, research_context
from research_retrieval import save_model


def project():
    return Project(name='Meal Log', platform='iOS', status='launched', category='fitness',
                   description='Track meals and calories using a photo of your food.')


def test_full_publisher_details_survive_without_overwriting_private_brief():
    original = project()
    enriched = research_project(original, {'title':'Meal Log', 'details':{
        'description':'Photograph food to log calories. Privacy policy Contact us at hidden@example.com'}})
    assert 'Photograph food to log calories.' in enriched.description
    assert 'Privacy policy' not in enriched.description
    assert 'hidden@example.com' not in enriched.description
    assert original.description == 'Track meals and calories using a photo of your food.'


def test_unsupported_problem_inference_fails_instead_of_becoming_context():
    with pytest.raises(ValueError, match='source evidence'):
        grounded_understanding(project(), {'job':'Find recipes', 'job_quote':'Invented publisher claim'})


def test_confirmed_problem_wins_over_inferred_context():
    p = project().model_copy(update={'problem':'Manual calorie logging is slow', 'audience':'Busy adults'})
    save_model(p, {'product_understanding':{'job':'Log calories from food photos', 'problem':'Other problem','audience':'Other audience'}})
    result = research_context(p)
    assert result['customer_problem'] == p.problem
    assert result['audience'] == p.audience
    assert result['product_job'] == 'Log calories from food photos'


def test_different_product_jobs_can_run_at_the_same_time():
    barrier = threading.Barrier(2)
    def run(key):
        with research_lock(key):
            barrier.wait(timeout=2)
            return key
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(run, ['a','b'])) == {'a','b'}
    assert not RESEARCH_LOCKS


def test_same_product_jobs_are_deduplicated_and_locks_released():
    count = 0
    def run(_):
        nonlocal count
        with research_lock('same'):
            count += 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, range(30)))
    assert count == 30
    assert not RESEARCH_LOCKS


def test_failed_product_analysis_does_not_launch_broad_searches(monkeypatch):
    import research_providers
    from live_discovery import research_live, ResearchUnavailable
    monkeypatch.setattr(research_providers, 'configuration', lambda: {'enabled':True, 'evaluation':True})
    def unavailable(_):
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(research_providers, 'search_brief', unavailable)
    def forbidden(*args):
        pytest.fail('A generic search must not replace failed product analysis')
    with pytest.raises(ResearchUnavailable, match='Product analysis'):
        research_live(project(), search=forbidden)


def test_evaluator_receives_grounded_job_and_rejects_target_product_as_competitor(monkeypatch):
    import httpx
    import research_providers
    p = project()
    save_model(p, {'product_understanding':{'job':'Log calories from food photos', 'problem':'Manual food logging', 'audience':'People tracking nutrition'}})
    source = {'id':'s1', 'platform':'Instagram', 'kind':'Video', 'title':'Meal Log photo tracking',
              'summary':'Meal Log logs calories from photos of meals.'}
    def respond(url, **kwargs):
        prompt = kwargs['json']['contents'][0]['parts'][0]['text']
        assert 'Log calories from food photos' in prompt
        import json
        verdict = {'id':'s1', 'intent':'competitor', 'relevance':.95,
                   'evidence_quote':source['summary'], 'competitor_name':'Meal Log',
                   'competitor_job_quote':'logs calories from photos of meals.'}
        return httpx.Response(200, request=httpx.Request('POST',url),
          json={'candidates':[{'content':{'parts':[{'text':json.dumps({'items':[verdict]})}]}}]})
    monkeypatch.setenv('GEMINI_API_KEY','fixture')
    monkeypatch.setattr(research_providers, 'authorize', lambda *args:None)
    monkeypatch.setattr(httpx, 'post', respond)
    assert research_providers.evaluate_batch(p, [source]) == {}


def test_planner_enforces_schema_and_cleans_operators(monkeypatch):
    import httpx, json
    import research_providers
    p = project()
    quote = p.description
    understanding = {key:value for field in ('job','problem','audience') for key,value in ((field,'People tracking calories'),(field+'_quote',quote))}
    payload = {'product_understanding':understanding,
               'for_you':[f'site:tiktok.com food logging frustration {i}' for i in range(6)],
               'competitors':[f'photo calorie tracking apps {i}' for i in range(6)],
               'conversations':[f'need help tracking calories {i}' for i in range(18)],
               'subreddits':['nutrition'], 'adjacent_topics':['food logging']}
    def respond(url, **kwargs):
        schema = kwargs['json']['generationConfig']['responseJsonSchema']
        assert schema['properties']['conversations']['minItems'] == 18
        return httpx.Response(200, request=httpx.Request('POST',url),
          json={'candidates':[{'content':{'parts':[{'text':json.dumps(payload)}]}}]})
    monkeypatch.setenv('GEMINI_API_KEY','fixture')
    monkeypatch.setattr(research_providers, 'authorize', lambda *args:None)
    monkeypatch.setattr(httpx, 'post', respond)
    monkeypatch.setattr(__import__('collect_public'), 'subscribe', lambda *args:None)
    plan = research_providers.search_brief(p)
    assert len(plan['conversations']) == 18
    assert all('site:' not in phrase for phrase in plan['for_you'])


def test_description_supports_twelve_hundred_characters():
    from pydantic import ValidationError
    data=project().model_dump()
    assert len(Project(**{**data,'description':'a'*1200}).description)==1200
    with pytest.raises(ValidationError):Project(**{**data,'description':'a'*1201})


def test_more_than_three_competitors_are_preserved():
    names=['Alpha','Beta','Gamma','Delta','Epsilon','Zeta']
    p=Project(**{**project().model_dump(),'competitors':names})
    assert p.competitors==names
    assert research_context(p)['known_competitors']==names


def test_public_profile_photo_does_not_use_product_artwork(monkeypatch):
    import app
    monkeypatch.setattr(app,'safe_asset',lambda value:value if value.startswith('https://cdn.example/') else '')
    photo='https://cdn.example/avatar.jpg'
    assert app.social_profile_image('https://instagram.com/designer/',photo,[])==photo
    assert app.social_profile_image('https://x.com/designer','',[{'@type':'Person','image':{'url':photo}}])==photo
    assert app.social_profile_image('https://instagram.com/p/post/',photo,[])==''
    assert app.social_profile_image('https://example.com/app',photo,[])==''
    assert app.social_profile_image('https://x.com/designer','',[])==''
