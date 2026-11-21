"""Source preferences remain private, bounded and separate from competitor ownership."""
import json
import pytest
from pydantic import ValidationError
from app import Project
from native_collection import queries
from research_routing import media_plan
from research_retrieval import cached_model, save_model, connect, public_candidate_rows
from research_providers import remember_public_sources


def product(**updates):
    fields=dict(name='InvoiceTrail',platform='Web',status='launched',category='other',
                description='Help freelancers collect overdue invoices and manage late client payments.',
                keywords=['invoice','payment'])
    return Project(**(fields|updates))


def test_old_identity_unchanged_and_follows_round_trip():
    baseline=product().model_dump()
    assert 'followed_sources' not in baseline
    p=product(followed_sources=[dict(name='freelance bookkeeping',platform='Instagram')])
    assert Project(**p.model_dump()).followed_sources[0].kind=='topic'
    assert p.model_dump()!=baseline
    assert p.keywords==['invoice','payment']


def test_bad_preferences_rejected_without_fetching():
    for source in [dict(name='<script>',platform='X'),dict(name=' ',platform='X'),
                   dict(name='name',platform='Unknown'),dict(name='name',platform='X',kind='competitor'),
                   dict(name='name',platform='X',kind='account',url='file:///private/secret'),
                   dict(name='name',platform='X',url='https://user:pass@x.com/account')]:
        with pytest.raises(ValidationError):product(followed_sources=[source])
    with pytest.raises(ValidationError):product(followed_sources=[dict(name='topic',platform='X')]*101)


def test_followed_topic_targets_only_selected_network_and_never_competitor_lane():
    p=product(followed_sources=[dict(name='freelance bookkeeping',platform='Instagram')])
    model={'for_you':['invoice routine'],'competitors':['invoice reminder apps']}
    assert 'freelance bookkeeping' in queries(p,model,'for_you','Instagram')
    assert 'freelance bookkeeping' not in queries(p,model,'for_you','TikTok')
    assert 'freelance bookkeeping' not in queries(p,model,'competitors','Instagram')
    plan=media_plan({'tiktok':['invoice routine ideas','invoice reminder apps']},p)
    assert dict(platform='Instagram',lane='discover',phrases=['freelance bookkeeping']) in plan
    assert not any(t['platform']=='TikTok' and 'freelance bookkeeping' in t['phrases'] for t in plan)


def test_watchlist_change_reuses_understanding_without_reusing_old_conversation_plan():
    base=product()
    save_model(base,{'product_understanding':{'job':'Collect overdue invoices'},'for_you':['freelancer routines'],
                     'native_x_query_plan':['old query'],'native_x_query_plan_policy':6})
    changed=product(followed_sources=[dict(name='freelance bookkeeping',platform='X')])
    model=cached_model(changed)
    assert model['product_understanding']['job']=='Collect overdue invoices'
    assert 'native_x_query_plan' not in model
    save_model(changed,{**model,'native_x_query_plan':['new query']})
    assert cached_model(base)['native_x_query_plan']==['old query']
    assert cached_model(changed)['native_x_query_plan']==['new query']


def test_followed_topics_retrieve_older_public_posts_without_leaking_preferences():
    import time
    target={'id':'followed','platform':'Instagram','kind':'Video','url':'https://www.instagram.com/p/abc123/',
            'title':'Bookkeeping for freelancers','summary':'Freelance bookkeeping workflows'}
    remember_public_sources([target])
    with connect() as db:
        db.execute('UPDATE public_sources SET created=?',(time.time()-1000,))
        db.executemany('INSERT INTO public_sources VALUES(?,?,?)',[
            (f'https://www.instagram.com/p/other{i}/',json.dumps({**target,'id':str(i),'title':'Bread baking','summary':'Sourdough recipe','url':f'https://www.instagram.com/p/other{i}/'}),time.time()) for i in range(500)])
    p=product(followed_sources=[dict(name='bookkeeping',platform='Instagram')])
    with connect() as db:
        rows=public_candidate_rows(db,p)
        assert any(json.loads(r)['id']=='followed' for r in rows)
        assert all('followed_sources' not in json.loads(r) for r in rows)


def test_account_identity_is_exact_and_never_a_competitor_claim():
    from source_preferences import matches
    follow=product(followed_sources=[dict(name='@maker',platform='X',kind='account',url='https://x.com/maker')]).followed_sources[0]
    post={'platform':'X','url':'https://x.com/maker/status/1234567890','author':'Maker Studio','title':'A useful invoice workflow'}
    assert matches(post,follow)
    assert not matches({**post,'url':'https://x.com/notmaker/status/1234567890','author':'notmaker'},follow)
    assert not matches({**post,'platform':'Instagram'},follow)
    assert 'competitor' not in post


def test_preference_change_reuses_factual_verdict_but_not_other_product_verdict():
    from research_providers import evaluation_key
    post={'id':'one','title':'Invoice routine','summary':'Collecting overdue invoices'}
    base=product()
    followed=product(followed_sources=[dict(name='bookkeeping',platform='X')])
    assert evaluation_key(base,post,'model')==evaluation_key(followed,post,'model')
    different=product(description='Help home cooks plan weekly meals and reduce leftover food.')
    assert evaluation_key(base,post,'model')!=evaluation_key(different,post,'model')


def test_coverage_distinguishes_missing_collection_from_unreviewed_and_rejected():
    from workspace_refresh import coverage
    candidates=[{'platform':'X','url':'x/1'},{'platform':'Reddit','url':'r/1'},{'platform':'TikTok','url':'t/1'}]
    report=coverage(candidates,[candidates[1],candidates[2]],[candidates[2]])
    assert report['Instagram']['status']=='needs_collection'
    assert report['X']['status']=='needs_review'
    assert report['Reddit']['status']=='no_qualified_matches'
    assert report['TikTok']['accepted']==1


def test_conversation_schedule_rotates_user_topics_after_customer_intent_queries():
    p=product(followed_sources=[dict(name='late client payments',platform='Reddit')])
    model={'native_reddit_query_plan':['unpaid invoice','payment reminder','freelance clients']}
    planned=queries(p,model,'conversations','Reddit')
    assert planned[:3]==model['native_reddit_query_plan']
    assert 'late client payments' in planned
    assert 'late client payments' not in queries(p,{'native_x_query_plan':['unpaid invoice']},'conversations','X')
