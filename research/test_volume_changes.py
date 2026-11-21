from datetime import datetime,timedelta,timezone
import sqlite3

from app import preserve_research_diagnostics
import competitor_accounts as accounts
import research_providers as providers
from research_quality import select_results
import workspace_refresh
from test_workspace_refresh import post,product,reviewed,workspace


def test_keeps_real_rejections_and_funnel_after_final_selection():
    old={'id':'a','reason':'Unrelated'}
    final={'id':'b','reason':'Removed on delivery'}
    report={'rejected':[old,final],'lane_counts':{'discover':1}}
    funnel={'pending_evaluation':95,'coverage':{'X':{'collected':77}}}
    preserve_research_diagnostics(report,{'quality_report':{'rejected':[old],'retrieval':{'native_collections':[]}},'refresh':funnel})
    assert report['rejected']==[old,final]
    assert report['refresh']==funnel and report['retrieval']=={'native_collections':[]}


def test_recovered_quotes_are_exact_original_substrings():
    source='A post I “really\u200b need”\n  to track meals. Nothing else.'
    assert providers.original_quote('I "really need" to track meals.',source)=='I “really\u200b need”\n  to track meals.'
    assert providers.original_quote('Tracking meals 🎉 starts here.','Tracking meals🎉 starts here.')=='Tracking meals🎉 starts here.'
    approximate='I really need to track my meals every day.'
    requested='I really need to trak my meals every day.'
    assert providers.original_quote(requested,approximate)==approximate
    assert providers.original_quote('I was actually discussing quarterly taxes.',source) is None


def test_bad_quote_retries_only_its_item_once(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
    calls=[]
    verbatim='I need help logging my meals without typing everything.'
    good={'id':'a','title':'Nutrition','summary':verbatim,'platform':'Reddit'}
    bad={**good,'id':'b'}
    def generate(key,prompt,schema,*args):
        ids=schema['properties']['items']['items']['properties']['id']['enum']
        calls.append(ids)
        quote=verbatim if len(calls)==2 else 'This quotation does not appear in the original post.'
        base={'intent':'audience_problem','relevance':.9,'need_status':'unresolved'}
        return {'items':[{'id':item,**base,'evidence_quote':verbatim if item=='a' else quote,
                          'request_quote':verbatim} for item in ids]},'test-model'
    monkeypatch.setattr(providers,'gemini_generate',generate)
    checked=providers.evaluate_batch(product(),[good,bad])
    assert calls==[['a','b'],['b']]
    assert checked.recovered_quotes==1 and checked.unrecoverable_quotes==0
    assert checked['b']['evidence_quote']==verbatim


def test_profile_identity_requires_matching_name_and_product_link():
    assert accounts.profile('https://www.tiktok.com/@mealwiz')==('TikTok','mealwiz')
    assert accounts.profile('https://x.com/mealwiz/status/10') is None
    assert accounts.official_handle({'username':'daily_meals','fullName':'MealWiz','externalUrl':'https://mealwiz.com/app'},'MealWiz')=='daily_meals'
    assert accounts.official_handle({'username':'mealwiz','externalUrl':'https://irrelevant.example/app'},'MealWiz') is None
    assert accounts.actor_input('TikTok','mealwiz',True)['profiles']==['mealwiz']
    assert accounts.actor_input('Instagram','mealwiz',True)['resultsLimit']==20
    assert accounts.actor_input('X','mealwiz',True)['scrapeType']=='userPosts'


def test_official_competitor_still_needs_literal_capability_and_engagement():
    project=product().model_copy(update={'competitors':['MealWiz, https://x.com/mealwiz']})
    with accounts.connect() as db:
        accounts.account_rows(project)
        from live_discovery import cache_key
        db.execute('INSERT INTO competitor_accounts VALUES(?,?,?,?,?,?)',(cache_key(project),'MealWiz','X','mealwiz','supplied_profile',1))
    today=datetime.now(timezone.utc).isoformat()
    quote='Scan meals from a photo and get calorie estimates.'
    source={**post('123'),'platform':'X','url':'https://x.com/mealwiz/status/123','author':'mealwiz',
            'title':quote,'summary':quote,'evidence':{'type':'original_platform_post'},
            'metrics':{'provider':'apify','checked_at':today,'views':2300,'likes':20},
            'evaluation':{'provider':'gemini','checked_at':today,'policy_version':17,'intent':'competitor','relevance':.9,
                          'evidence_quote':quote,'competitor_job_quote':quote,'competitor_name':'MealWiz'}}
    selected,report=select_results(project,[source],require_evaluation=True,native_only=True)
    assert selected[0]['publisher_basis']=='official_account' and report['lane_counts']['competitors']==1
    for change in ({'metrics':{}},{'published_at':None},{'url':'https://x.com/fan/status/123'},{'evaluation':{**source['evaluation'],'competitor_job_quote':'Made up'}}):
        selected,_=select_results(project,[{**source,**change}],require_evaluation=True,native_only=True)
        assert not selected


def test_history_is_owner_scoped_requires_exact_brief_and_expires(monkeypatch):
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE projects(id TEXT,owner TEXT)')
    db.execute("INSERT INTO projects VALUES('project','owner')")
    brief=product()
    newer=post()
    older=post('old',days=31)
    workspace_refresh.archive(db,'project',workspace([newer,older]))
    monkeypatch.setattr(workspace_refresh,'cached_evaluations',lambda p, sources:[reviewed(source) for source in sources] if p==brief else [])
    assert workspace_refresh.archived(db,'project','another',brief)==[]
    assert workspace_refresh.archived(db,'project','owner',brief.model_copy(update={'name':'Different'}))==[]
    archived=workspace_refresh.archived(db,'project','owner',brief)
    result=workspace_refresh.refresh(brief,workspace(),[],history=archived)
    assert [source['id'] for source in result['conversations']]==['abc']


def test_conversation_capacity_keeps_fifteen_per_network_and_uses_thirty_day_total():
    records=[]
    now=datetime.now(timezone.utc)
    for platform,count in [('X',66),('Reddit',15)]:
        for index in range(count):
            source=post(f'{platform.lower()}{index}',days=8 if platform=='X' else 20)
            quote=f"Can anyone recommend a food tracker that helps with problem number {index} on {platform}?"
            source.update(platform=platform,title=quote,summary=quote,author=f'author{index}',published_at=(
                now-timedelta(days=8 if platform=='X' else 20,minutes=index)).isoformat())
            records.append(reviewed(source))
    selected,quality=select_results(product(),records,require_evaluation=True)
    assert len(selected)==60 and quality['conversation_platform_counts']=={'Reddit':15,'X':45}
    assert quality['recent_conversation_count']==0
    assert not any(reason.startswith(('Conversations:','Reddit:','X:')) for reason in quality['blockers'])


def test_checked_workflow_discussion_is_labelled_without_implying_buying_intent():
    now=datetime.now(timezone.utc).isoformat()
    quote='We spend hours manually logging meals after dinner when everyone is tired.'
    source={**post('workflow'),'title':quote,'summary':quote,
            'evidence':{'type':'original_platform_post'},
            'evaluation':{'provider':'gemini','checked_at':now,'intent':'creative_reference',
                          'relevance':.82,'evidence_quote':quote,'need_type':'niche_discussion'}}
    selected,_=select_results(product(),[source],require_evaluation=True,native_only=True)
    assert selected[0]['intent']=='conversations'
    assert selected[0]['conversation_signal']=={'type':'discussion','quote':quote}


def test_describing_my_app_does_not_make_an_audience_request_an_ad():
    from research_quality import route_source
    assert route_source({'platform':'Reddit','title':'My app keeps losing meal entries.',
                         'summary':'Does anyone recommend a meal logging app with backup?'})=='conversations'
