from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from research_quality import route_source,attention,select_results
from provider_budget import reserve,BudgetExceeded
from research_providers import evaluate,start_media_run,ProviderNotConfigured,normalize_media

PROJECT=SimpleNamespace(problem='Traders miss chart setups while away from charts',description='A chart pattern scanner and market alerts')

def source(text,platform='Reddit'):
 from datetime import datetime,timezone
 return {'id':text[:20],'title':text,'summary':text,'platform':platform,'url':'https://reddit.com/r/trading/comments/abc/post/','kind':'Discussion','published_at':datetime.now(timezone.utc).isoformat(),'matched_terms':['charts','setups','alerts']}


@pytest.mark.parametrize('days',[31,90,365,None])
def test_old_or_undated_requests_cannot_enter_current_conversations(days):
 from datetime import datetime,timezone,timedelta
 s=source('Looking for a chart scanner to avoid missing setups.')
 s['published_at']=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat() if days is not None else None
 chosen,report=select_results(PROJECT,[s])
 assert chosen==[]
 assert any('last 30 days' in item['reason'] for item in report['rejected'])

@pytest.mark.parametrize('text',[
 'I built a pattern scanner for my own trading. Does anyone else automate this?',
 'Finally set up an AI agent: I built a chart alert platform.',
 'Veskald, a no-code platform for systematic crypto trading. Our platform sends alerts.',
 'I have just launched my app, a chart alert service.',
])
def test_builder_promotions_do_not_enter_audience_conversations(text):
 assert route_source(source(text))=='competitors'

@pytest.mark.parametrize('text',[
 'Looking for any service that scans the market for patterns and sends me notifications.',
 'I keep missing chart setups while away. How do you handle this?',
 'Does anyone know a scanner that alerts me when a double bottom forms?',
])
def test_audience_requests_remain_in_conversations(text):assert route_source(source(text))=='conversations'

def test_explicit_burden_can_omit_first_person_subject():
 assert route_source(source('Been checking invoices for too long. Need to get back to client work.'))=='conversations'
 assert route_source(source('Been reviewing charts for too long.'))=='conversations'
 assert route_source(source('Been reviewing charts this morning.'))=='reject'
 quoted=source('Been reviewing charts for too long.')
 quoted['title']=''
 assert route_source(quoted)=='conversations'

def test_unverified_numbers_do_not_pass_attention_gate():
 s=source('A chart tutorial','Instagram');s['metrics']={'views':1000000}
 assert attention(s)['status']=='unverified'
 s['metrics']={'provider':'apify','checked_at':'2026-11-03','likes':46,'comments':7}
 assert attention(s)['status']=='measured'
 s['metrics']['views']=25000
 assert attention(s)['status']=='measured'

def test_no_paid_call_without_configuration(monkeypatch):
 monkeypatch.delenv('GEMINI_API_KEY',raising=False);monkeypatch.delenv('APIFY_TOKEN',raising=False)
 with pytest.raises(ProviderNotConfigured):evaluate(PROJECT,[])
 with pytest.raises(ProviderNotConfigured):start_media_run('Instagram',['https://instagram.com/p/abc/'])

def test_missing_metrics_remain_null():
 assert normalize_media({},'Instagram')['metrics']['views'] is None
 assert normalize_media({'likesCount':46},'Instagram')['metrics']['likes']==46

def test_concurrent_reservations_cannot_exceed_five_dollars(tmp_path):
 path=tmp_path/'budget.sqlite3'
 # Initialize before concurrent access to focus on atomic spend reservation.
 reserve(path,'initial',100000)
 def attempt(_):
  try:reserve(path,'apify',100000);return True
  except BudgetExceeded:return False
 with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(60)))
 assert sum(results)==49


def test_budget_increase_preserves_spend_and_enforces_approved_hard_cap(tmp_path):
 path=tmp_path/'budget.sqlite3'
 reserve(path,'previous-evaluation',4_410_000)
 reserve(path,'approved-extension',5_000_000,ceiling_microusd=10_000_000)
 with pytest.raises(BudgetExceeded):reserve(path,'over-cap',700_000,ceiling_microusd=10_000_000)
 reserve(path,'remaining',590_000,ceiling_microusd=10_000_000)
 with pytest.raises(BudgetExceeded):reserve(path,'exhausted',1,ceiling_microusd=10_000_000)
 reserve(path,'approved-x-check-extension',100_000,ceiling_microusd=10_100_000)
 reserve(path,'approved-native-comparison',6_000_000,ceiling_microusd=16_100_000)
 reserve(path,'approved-november-20-extension',9_980_000,ceiling_microusd=26_080_000)
 reserve(path,'approved-second-november-20-extension',10_000_000,ceiling_microusd=36_080_000)
 reserve(path,'approved-third-november-20-extension',10_000_000,ceiling_microusd=46_080_000)
 reserve(path,'approved-november-21-validation',53_920_000,ceiling_microusd=100_000_000)
 with pytest.raises(BudgetExceeded):reserve(path,'beyond-hard-cap',1,ceiling_microusd=101_000_000)

def test_refresh_keeps_real_audience_request_and_moves_builder():
 question=source('Looking for a chart scanner to avoid missing setups.')
 promo=source('I built a chart scanner for my own trades.');promo['url']+='other'
 chosen,report=select_results(PROJECT,[promo,question])
 assert next(s for s in chosen if s['url']==question['url'])['section']=='conversations'
 assert next(s for s in chosen if s['url']==promo['url'])['competitor'] is True
 assert report['launch_ready'] is False


def test_semantic_evaluation_rejects_broad_topic_match():
 s=source('Learn technical analysis and charts for trading.')
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-03','intent':'irrelevant','relevance':.2,'evidence_quote':s['title']}
 selected,report=select_results(PROJECT,[s])
 assert selected==[]
 assert report['rejected'][0]['reason']=='Semantic evaluation rejected the problem match.'


def test_editorial_pain_and_working_alerts_are_not_unresolved_leads():
 s=source("Why manual chart watching costs you gains. The Data: Studies show traders miss setups. Simple formula: Pattern to alert. Real example: Alert pinged while I slept.")
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-06','intent':'audience_problem','relevance':.95,'evidence_quote':s['title'],'need_status':'unresolved','request_quote':s['title']}
 selected,report=select_results(PROJECT,[s],require_evaluation=True)
 assert selected==[]
 assert report['rejected'][0]['reason']=='No current unresolved audience need is evidenced.'


def test_working_solution_with_explicit_remaining_request_can_still_be_a_lead():
 s=source('My alert pinged too late. Is there any service that catches chart setups sooner?')
 selected,_=select_results(PROJECT,[s])
 assert selected[0]['section']=='conversations'


def test_fabricated_evidence_cannot_override_routing():
 s=source('I built a chart scanner for my own trades.')
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-03','intent':'audience_problem','relevance':1,'evidence_quote':'I need a chart scanner and have never built one.'}
 selected,_=select_results(PROJECT,[s])
 assert selected[0]['competitor'] is True


def test_retrieved_transcript_survives_reranking():
 s=source('Looking for a chart scanner to avoid missing setups.')
 s['analysis']={'transcript':'Retrieved spoken words','frames':[]}
 selected,_=select_results(PROJECT,[s])
 assert selected[0]['analysis']['transcript']=='Retrieved spoken words'


def test_generic_masterclass_does_not_qualify_as_problem_content():
 s=source('Technical analysis masterclass for beginners','TikTok')
 s['summary']='Chart analysis and market setups explained in our webinar.'
 selected,report=select_results(PROJECT,[s])
 assert selected==[]
 assert 'educational' in report['rejected'][0]['reason']


def test_resolved_ai_agent_story_is_not_an_audience_lead():
 s=source('finally set up an ai agent to watch the charts for me so i can actually sleep')
 s['summary']='I just need something to alert me when conditions match. Been testing a new agent setup. Honestly saved my sleep schedule. Curious what others are using.'
 assert route_source(s)=='reject'
 selected,report=select_results(PROJECT,[s])
 assert selected==[]


def test_failed_solution_with_explicit_remaining_need_is_kept():
 s=source('Finally set up chart alerts but still missing setups. Any better tools?')
 assert route_source(s)=='conversations'


def test_real_request_has_source_quote_instead_of_keyword_reason():
 s=source('Service that scans the market for patterns')
 s['summary']='Looking for any service that sends me a notification when chart patterns form.'
 selected,_=select_results(PROJECT,[s])
 assert selected[0]['conversation_signal']['type']=='request'
 assert s['summary'] in selected[0]['match_reason']


def test_live_evaluator_mode_cannot_fall_back_to_keyword_results():
 s=source('Looking for a chart scanner that alerts me to setups.')
 chosen,report=select_results(PROJECT,[s],require_evaluation=True)
 assert chosen==[]
 assert report['rejected'][0]['reason']=='Semantic evaluation is required but absent.'


def test_semantic_audience_lead_requires_an_unresolved_need_quote():
 s=source('Looking for a chart scanner that alerts me to setups.')
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-05','relevance':.95,'intent':'audience_problem','evidence_quote':s['title']}
 assert select_results(PROJECT,[s],require_evaluation=True)[0]==[]
 s['evaluation'].update(need_status='unresolved',request_quote=s['title'])
 assert select_results(PROJECT,[s],require_evaluation=True)[0][0]['intent']=='conversations'


def test_builder_pitch_never_becomes_for_you_even_if_model_misroutes_it():
 s=source('I built a chart scanner because I kept missing setups.')
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-06','relevance':.95,
                  'intent':'creative_reference','evidence_quote':s['title']}
 result,_=select_results(PROJECT,[s],require_evaluation=True)
 assert result==[]


def test_for_you_does_not_accept_a_semantic_match_without_measured_attention():
 s=source('Missing chart setups while at work','Instagram')
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-06','relevance':.95,
                  'intent':'creative_reference','evidence_quote':s['title']}
 assert select_results(PROJECT,[s],require_evaluation=True)[0]==[]
 s['metrics']={'provider':'apify','checked_at':'2026-11-06','plays':25000,'likes':1200}
 assert select_results(PROJECT,[s],require_evaluation=True)[0][0]['attention']['status']=='measured'


def test_model_cannot_turn_resolved_story_into_audience_need():
 s=source('finally set up an ai agent to watch the charts for me so i can actually sleep')
 s['summary']='Been testing a new agent setup. Honestly saved my sleep schedule. Has anyone else replaced screen time with AI monitoring?'
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-06','intent':'audience_problem','relevance':.99,
                 'evidence_quote':s['title'],'need_status':'unresolved',
                 'request_quote':'Has anyone else replaced screen time with AI monitoring?'}
 selected,report=select_results(PROJECT,[s],require_evaluation=True)
 assert selected==[]
 assert 'unresolved' in report['rejected'][0]['reason']


def test_client_work_is_not_automatically_a_software_competitor():
 s=source('I created a logo and banner for someone but he refused to pay upfront.','Instagram')
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-07','relevance':.95,'intent':'creative_reference','evidence_quote':s['title']}
 result,report=select_results(PROJECT,[s],require_evaluation=True)
 assert result==[]
 assert route_source(s)=='discover'
 assert 'retrieved engagement' in report['rejected'][0]['reason']


def test_broad_audience_overlap_cannot_become_a_conversation_lead():
    from types import SimpleNamespace
    from datetime import datetime,timezone
    project=SimpleNamespace(problem='Make daily meal logging faster',description='Photo calorie logger')
    text='I track calories already. Has anyone switched medications because this one stopped working?'
    source={'id':'wrong-job','url':'https://www.reddit.com/r/example/comments/abc123/help/',
        'platform':'Reddit','kind':'Post','title':'Medication alternatives','summary':text,
        'published_at':datetime.now(timezone.utc).isoformat(),
        'evaluation':{'provider':'gemini','checked_at':'2026-11-07','intent':'audience_problem','relevance':.5,
            'need_status':'unresolved','request_quote':'Has anyone switched medications because this one stopped working?',
            'evidence_quote':'I track calories already.'}}
    selected,report=select_results(project,[source],require_evaluation=True)
    assert not selected
    assert any('different task' in item['reason'] for item in report['rejected'])


def test_resuming_an_activity_is_not_a_request_for_help():
    from types import SimpleNamespace
    from datetime import datetime,timezone
    project=SimpleNamespace(problem='Make daily meal logging faster',description='Photo calorie logger')
    quote="I'm going back to calorie tracking and adding resistance training."
    text=quote+' Has anyone switched medication after it stopped working?'
    source={'id':'statement-not-need','url':'https://www.reddit.com/r/example/comments/abc123/help/',
        'platform':'Reddit','kind':'Post','title':'Medication alternatives','summary':text,
        'published_at':datetime.now(timezone.utc).isoformat(),
        'evaluation':{'provider':'gemini','checked_at':'2026-11-07','intent':'audience_problem','relevance':.65,
            'need_status':'unresolved','request_quote':quote,'evidence_quote':quote}}
    selected,report=select_results(project,[source],require_evaluation=True)
    assert not selected
    assert any('not itself' in item['reason'] for item in report['rejected'])


def test_natural_process_question_counts_as_an_unresolved_request():
    from research_quality import route_source
    assert route_source({'platform':'Reddit','title':'','summary':"What's your normal process when an invoice goes overdue and the client stops responding?"})=='conversations'
    assert route_source({'platform':'Reddit','title':'','summary':'How should I organise revision when my exams overlap?'})=='conversations'


@pytest.mark.parametrize('text',[
    'I hate doing it but should I start tracking calories?',
    'I sometimes hate my tracking app. It keeps adding the same meal twice.',
    'I am frustrated with invoicing clients who never pay on time.',
    'I feel overwhelmed trying to organise revision for three exams.',
])
def test_first_person_frustrations_do_not_require_trading_vocabulary(text):
    assert route_source({'platform':'Reddit','title':'','summary':text})=='conversations'


def test_verbatim_crossposts_from_same_author_are_one_reference():
    from copy import deepcopy
    first=source('I keep missing chart setups while at work. Looking for a scanner that alerts me when patterns form, so I can stop watching charts all day.')
    first.update(author='same-author',id='first')
    crosspost=deepcopy(first)
    crosspost.update(id='crosspost',url='https://reddit.com/r/other/comments/def/post/')
    crosspost['summary']+=' Thanks!'
    independent=deepcopy(first)
    independent.update(id='independent',author='another-author',url='https://reddit.com/r/trading/comments/ghi/post/')
    chosen,report=select_results(PROJECT,[first,crosspost,independent])
    assert len(chosen)==2
    assert any(item['reason']=='Duplicate author cross-post.' for item in report['rejected'])

@pytest.mark.parametrize('relief',[
    'I found a solution. No sleepless nights now.',
    'I found something that works and am getting back to actually living my life.',
])
def test_past_distress_plus_relief_is_not_reopened_by_a_general_question(relief):
    s=source('I used to keep missing chart setups.')
    s['summary']=relief+' Does anyone else have stories about getting burned out?'
    assert route_source(s)=='reject'
    s['summary']+=' I am still looking for alternatives because it does not work on my phone.'
    assert route_source(s)=='conversations'


def test_verified_rant_is_not_misrepresented_as_a_solution_request():
    s=source('I hate staring at charts all day.')
    s['summary']='I hate staring at charts all day.'
    s['evaluation']={'provider':'gemini','checked_at':'2026-11-08','intent':'audience_problem',
        'relevance':.9,'evidence_quote':s['summary'],'need_status':'unresolved','request_quote':s['summary']}
    chosen,_=select_results(PROJECT,[s],require_evaluation=True)
    assert chosen[0]['conversation_signal']['type']=='problem'
    assert chosen[0]['match_reason'].startswith('They describe this problem:')


def test_text_inspiration_does_not_fill_short_form_discover():
 s=source('My morning reflection routine has helped me build a writing habit.','X')
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-20','intent':'creative_reference','relevance':.9,'evidence_quote':s['title']}
 chosen,report=select_results(PROJECT,[s],require_evaluation=True)
 assert chosen==[] and 'short-form media' in report['rejected'][0]['reason']


def test_vague_cross_niche_media_cannot_pass_as_useful_discovery():
 s=source('Daily habits for a better life and happy morning.','Instagram')
 s['evaluation']={'provider':'gemini','checked_at':'2026-11-20','intent':'creative_reference','relevance':.5,'evidence_quote':s['title']}
 chosen,report=select_results(PROJECT,[s],require_evaluation=True)
 assert chosen==[] and 'concrete niche connection' in report['rejected'][0]['reason']


def test_relevant_niche_question_is_distinguished_from_a_buying_need():
 s=source('How do you handle chart analysis across multiple timeframes?','X')
 s['evaluation']={'provider':'gemini','policy_version':17,'checked_at':'2026-11-20',
                  'intent':'creative_reference','relevance':.9,'evidence_quote':s['title'],'need_status':'unclear','need_type':'not_applicable'}
 chosen,_=select_results(PROJECT,[s],require_evaluation=True)
 assert chosen[0]['intent']=='conversations'
 assert chosen[0]['conversation_signal']['type']=='question'
 assert 'asking for a solution' not in chosen[0]['match_reason']


def test_general_outcome_advice_cannot_masquerade_as_workflow_need():
 s=source('I track meals but my weight has stalled. How can I lose weight faster?')
 s['evaluation']={'provider':'gemini','policy_version':17,'checked_at':'2026-11-20',
                  'intent':'audience_problem','relevance':.9,'evidence_quote':s['title'],'request_quote':s['title'],
                  'need_status':'unresolved','need_type':'outcome_advice'}
 chosen,report=select_results(PROJECT,[s],require_evaluation=True)
 assert chosen==[] and 'outcome advice' in report['rejected'][0]['reason']


def test_local_editorial_question_requires_original_current_evidence():
    from datetime import datetime, timedelta, timezone

    post = source("Is there a particular detail in price action that most traders overlook?")
    post['evidence'] = {'type': 'original_platform_post'}
    post['evaluation'] = {
        'provider': 'local_editorial_review', 'checked_at': 'checked',
        'intent': 'audience_problem', 'need_type': 'niche_question', 'relevance': .85,
        'evidence_quote': post['title'], 'request_quote': post['title']
    }
    result, _ = select_results(PROJECT, [post], require_evaluation=True)
    assert result[0]['conversation_signal']['type'] == 'question'
    for invalid in (
        {**post, 'evidence': {'type': 'search_snippet'}},
        {**post, 'published_at': (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()},
    ):
        result, _ = select_results(PROJECT, [invalid], require_evaluation=True)
        assert not result


def test_native_competitor_needs_first_party_evidence():
    maker = "We've been working on a technical analysis dashboard"
    job = "Scans several charts at once for setups."
    item = source(maker)
    item['summary'] += ' ' + job
    item['evidence'] = {'type': 'original_platform_post'}
    item['metrics']={'provider':'apify','checked_at':'2026-11-20','score':16,'views':1200,'likes':22}
    item['evaluation'] = {'provider': 'gemini', 'policy_version': 15,
        'checked_at': '2026-11-06', 'intent': 'competitor', 'relevance': .95,
        'evidence_quote': maker, 'competitor_name': 'Technical Analysis Dashboard',
        'competitor_publisher_quote': maker, 'competitor_job_quote': job}
    assert select_results(PROJECT, [item], require_evaluation=True, native_only=True)[0][0]['competitor']
    item['evidence'] = {'type': 'indexed_public_post'}
    assert not select_results(PROJECT, [item], require_evaluation=True, native_only=True)[0]


@pytest.mark.parametrize('views,allowed',[(198,False),(999,False),(1_000,True),(2_600,True),(3_000,True),(None,False)])
def test_video_views_floor_depends_on_lane(views,allowed):
 from copy import deepcopy
 for lane in ('creative_reference','competitor'):
    text="We built a chart pattern scanning app that monitors setups automatically."
    candidate=source(text,'TikTok')
    candidate['kind']='Video'
    candidate['evidence']={'type':'original_platform_post'}
    candidate['metrics']={'provider':'apify','checked_at':'2026-11-20','views':views,'likes':20}
    candidate['evaluation']={'provider':'gemini','policy_version':15,'checked_at':'2026-11-20',
        'intent':lane,'evidence_quote':text,'relevance':.95,
        'competitor_name':'Chart Scanner','competitor_publisher_quote':text,'competitor_job_quote':text}
    if lane=='creative_reference':
        candidate.update(title='Using chart alerts to step away from my monitor',
                         summary='Using chart alerts to step away from my monitor')
        candidate['evaluation']['evidence_quote']=candidate['title']
    expected=allowed if lane=='creative_reference' else views is not None and views>=3000
    assert bool(select_results(PROJECT,[deepcopy(candidate)],require_evaluation=True,native_only=True)[0]) is expected


def test_local_competitor_review_requires_an_original_maker_quote_and_product_job():
 text="I'm the founder of ChartMate. The app scans charts for candlestick patterns."
 candidate=source(text)
 candidate['evidence']={'type':'original_platform_post'}
 candidate['metrics']={'provider':'apify','checked_at':'2026-11-20','score':16,'views':1200,'likes':22}
 candidate['evaluation']={'provider':'local_editorial_review','checked_at':'2026-11-20','intent':'competitor',
     'evidence_quote':text,'relevance':.88,'competitor_name':'ChartMate',
     'competitor_publisher_quote':"I'm the founder of ChartMate.",
     'competitor_job_quote':'The app scans charts for candlestick patterns.'}
 assert select_results(PROJECT,[candidate],native_only=True)[0][0]['competitor']
 candidate['evaluation']['competitor_publisher_quote']='Made-up ownership claim.'
 assert not select_results(PROJECT,[candidate],native_only=True)[0]


def test_general_advice_cannot_be_classified_as_a_software_recommendation():
 quote='Does anyone have any recommendations or advice? I want to take this seriously.'
 item=source(quote)
 item['evaluation']={'provider':'gemini','policy_version':17,'checked_at':'2026-11-20',
     'intent':'audience_problem','need_type':'software_recommendation','evidence_quote':quote,
     'request_quote':quote,'need_status':'unresolved','relevance':.90}
 assert not select_results(PROJECT,[item],require_evaluation=True)[0]


@pytest.mark.parametrize('platform,kind,metrics,accepted',[
    ('TikTok','Video',{'views':2600,'likes':100},False),
    ('TikTok','Video',{'views':42000,'likes':0,'comments':0},False),
    ('Instagram','Video',{'views':42000,'likes':1},False),
    ('Instagram','Video',{'views':42000,'likes':18},True),
    ('X','Post',{'views':20,'likes':12},False),
    ('X','Post',{'views':1200,'likes':1},False),
    ('X','Post',{'views':1200,'comments':6},True),
    ('Reddit','Post',{'score':13},True),
])
def test_competitor_engagement_uses_real_platform_metrics(platform,kind,metrics,accepted):
    from research_quality import has_competitor_engagement
    source={'platform':platform,'kind':kind,'metrics':{'provider':'apify','checked_at':'2026-11-20',**metrics}}
    assert has_competitor_engagement(source) is accepted
    source['metrics'].pop('provider')
    assert not has_competitor_engagement(source)


def test_explicit_request_for_automation_routes_to_conversations():
    from research_quality import route_source

    post = {
        'platform': 'X',
        'title': '',
        'summary': 'Who has found something that works for automated strategies, with alerts and proper backtesting?',
    }
    assert route_source(post) == 'conversations'
