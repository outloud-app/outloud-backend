"""Provider contract and reuse tests. All HTTP responses are local fixtures."""
import json
import httpx
import pytest
import research_providers as module


def test_pending_run_does_not_fetch_dataset(monkeypatch):
 monkeypatch.setenv('APIFY_TOKEN','test-placeholder')
 calls=[]
 def respond(request):
  calls.append(request.url.path)
  return httpx.Response(200,json={'data':{'status':'RUNNING'}})
 with httpx.Client(transport=httpx.MockTransport(respond)) as client:
  with pytest.raises(module.MediaPending):module.collect_media_run({'run_id':'abc123','dataset_id':'data123'},client)
 assert calls==['/v2/actor-runs/abc123']


def test_finished_run_reads_bounded_dataset(monkeypatch):
 monkeypatch.setenv('APIFY_TOKEN','test-placeholder')
 def respond(request):
  if '/actor-runs/' in request.url.path:
   assert request.url.params['waitForFinish']=='12'
   return httpx.Response(200,json={'data':{'status':'SUCCEEDED'}})
  assert request.url.params['limit']=='20'
  return httpx.Response(200,json=[{'likesCount':500}])
 with httpx.Client(transport=httpx.MockTransport(respond)) as client:
  assert module.collect_media_run({'run_id':'abc123','dataset_id':'data123'},client)==[{'likesCount':500,'_outloud_collection_status':'complete'}]


def test_refresh_reuses_pending_run_and_completed_measurements(monkeypatch,tmp_path):
 monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','1');monkeypatch.setenv('APIFY_TOKEN','test-placeholder');monkeypatch.setenv('OUTLOUD_MEDIA_START_ALLOWED','1')
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'media.sqlite3'))
 starts=[];polls=[]
 monkeypatch.setattr(module,'start_media_run',lambda platform,urls:starts.append(urls) or {'run_id':'abc123','dataset_id':'data123'})
 def collect(run):
  polls.append(run)
  if len(polls)==1:raise module.MediaPending()
  return [{'url':'https://www.instagram.com/reel/example/','likesCount':1250,'videoViewCount':25000,'displayUrl':'https://scontent.cdninstagram.com/post.jpg'}]
 monkeypatch.setattr(module,'collect_media_run',collect)
 sources=[{'id':'s1','url':'https://instagram.com/reel/example/','platform':'Instagram','kind':'Video','summary':'Actual indexed caption'}]
 first,issues=module.enrich_media(sources);assert issues and 'metrics' not in first[0]
 second,issues=module.enrich_media(sources);assert issues==[] and second[0]['metrics']['views']==25000
 third,issues=module.enrich_media(sources);assert third[0]['media']['poster'].endswith('post.jpg')
 assert len(starts)==1 and len(polls)==2


def test_provider_cannot_replace_post_with_unrequested_url(monkeypatch,tmp_path):
 monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','1');monkeypatch.setenv('APIFY_TOKEN','test-placeholder');monkeypatch.setenv('OUTLOUD_MEDIA_START_ALLOWED','1')
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'media.sqlite3'))
 monkeypatch.setattr(module,'start_media_run',lambda *args:{'run_id':'abc','dataset_id':'def'})
 monkeypatch.setattr(module,'collect_media_run',lambda run:[{'url':'https://instagram.com/reel/unrelated/','likesCount':50000}])
 sources=[{'id':'s1','url':'https://instagram.com/reel/example/','platform':'Instagram','kind':'Video'}]
 result,_=module.enrich_media(sources)
 assert 'metrics' not in result[0]


@pytest.mark.parametrize('url',['https://cdninstagram.com.evil.com/a.jpg','http://cdninstagram.com/a.jpg','https://user:password@cdninstagram.com/a.jpg','javascript:alert(1)'])
def test_media_images_reject_untrusted_hosts(url):assert module.trusted_media_url(url)==''


def test_reject_bad_run_id_before_http(monkeypatch):
 monkeypatch.setenv('APIFY_TOKEN','test-placeholder')
 with pytest.raises(ValueError):module.collect_media_run({'run_id':'../../elsewhere','dataset_id':'valid'})


def test_paused_collection_reuses_matching_completed_post_across_batches(monkeypatch,tmp_path):
 import sqlite3,time
 monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','1');monkeypatch.setenv('APIFY_TOKEN','test-placeholder')
 monkeypatch.setenv('OUTLOUD_MEDIA_START_ALLOWED','0')
 path=tmp_path/'media.sqlite3';monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(path))
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE media_jobs(key TEXT PRIMARY KEY,run TEXT,rows TEXT,created REAL)')
  observed=time.time()-3600
  db.execute('INSERT INTO media_jobs VALUES(?,?,?,?)',('previous-batch',json.dumps({'platform':'Instagram'}),json.dumps([{'url':'https://www.instagram.com/reel/example/','likesCount':1250,'videoViewCount':25000}]),observed))
 def forbidden(*args):raise AssertionError('A refresh must not start a new paid run')
 monkeypatch.setattr(module,'start_media_run',forbidden)
 sources=[{'id':'s1','url':'https://instagram.com/reel/example/','platform':'Instagram','kind':'Video'}]
 result,issues=module.enrich_media(sources)
 assert result[0]['metrics']['views']==25000
 from datetime import datetime
 assert abs(datetime.fromisoformat(result[0]['metrics']['checked_at']).timestamp()-observed)<1
 assert issues==[]


def test_timed_out_run_reuses_completed_rows_without_starting_a_new_run(monkeypatch):
 monkeypatch.setenv('APIFY_TOKEN','test-placeholder')
 def respond(request):
  if '/actor-runs/' in request.url.path:return httpx.Response(200,json={'data':{'status':'TIMED-OUT'}})
  return httpx.Response(200,json=[{'url':'https://instagram.com/reel/example/','likesCount':900},None])
 with httpx.Client(transport=httpx.MockTransport(respond)) as client:
  rows=module.collect_media_run({'run_id':'abc123','dataset_id':'data123'},client)
 assert len(rows)==1 and rows[0]['_outloud_collection_status']=='partial'
 assert rows[0]['likesCount']==900


def test_failed_run_is_not_presented_as_complete(monkeypatch):
 monkeypatch.setenv('APIFY_TOKEN','test-placeholder')
 def respond(request):return httpx.Response(200,json={'data':{'status':'FAILED'}})
 with httpx.Client(transport=httpx.MockTransport(respond)) as client:
  with pytest.raises(RuntimeError):module.collect_media_run({'run_id':'abc123','dataset_id':'data123'},client)


def test_direct_search_payload_does_not_enable_paid_addons():
 payload=module.tiktok_discovery_input(['missing trading setups while away'],15)
 assert payload['searchSection']=='/video'
 assert payload['resultsPerPage']==15
 assert payload['downloadSubtitlesOptions']=='NEVER_DOWNLOAD_SUBTITLES'
 assert payload['shouldDownloadVideos'] is False
 assert 'videoSearchSorting' not in payload and 'videoSearchDateFilter' not in payload


@pytest.mark.parametrize('phrases,limit', [([],15),(['x'],15),(['https://example.com'],15),(['chart watching'],100),(['chart watching'],True)])
def test_direct_search_rejects_unbounded_or_invalid_requests(phrases,limit):
 with pytest.raises(ValueError):module.tiktok_discovery_input(phrases,limit)


def test_direct_search_requires_its_own_enable_switch(monkeypatch):
 monkeypatch.delenv('OUTLOUD_MEDIA_SEARCH_ALLOWED',raising=False)
 with pytest.raises(module.ProviderNotConfigured):module.start_tiktok_discovery(['chart watching fatigue'])


def test_platform_search_rows_keep_original_text_media_and_provenance():
 rows=[{'webVideoUrl':'https://www.tiktok.com/@person/video/1234567890','text':'Tired of watching charts all day and missing setups.','playCount':20000,'authorMeta':{'name':'person'},'videoMeta':{'coverUrl':'https://p16-sign.tiktokcdn.com/poster.jpg'},'createTimeISO':'2026-11-06T00:00:00Z'},
       {'webVideoUrl':'https://example.com/untrusted','text':'Do not accept this result.'}]
 result=module.sources_from_media_rows(rows,'TikTok')
 assert len(result)==1 and result[0]['metrics']['views']==20000
 assert result[0]['author']=='person'
 assert result[0]['media']['poster'].endswith('poster.jpg')
 assert result[0]['evidence']['type']=='original_platform_post'
 assert 'transcript' not in result[0]


def test_malformed_optional_media_fields_do_not_crash_the_batch():
 normalized=module.normalize_media({'videoMeta':None,'text':{'not':'a caption'},'playCount':float('inf'),'likesCount':True},'TikTok')
 assert normalized['caption']=='' and normalized['metrics']['views'] is None
 assert normalized['metrics']['likes'] is None
 assert module.sources_from_media_rows([{'webVideoUrl':'https://www.tiktok.com/@person/video/1234567890','text':'A valid source caption about missing chart setups.','authorMeta':'invalid','videoMeta':None}],'TikTok')[0]['author']=='TikTok creator'


def test_remembered_public_sources_are_candidates_not_shared_verdicts(monkeypatch,tmp_path):
 from app import Project
 import sqlite3,time
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'public.sqlite3'))
 monkeypatch.setenv('OUTLOUD_PAID_RESEARCH','1');monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 source=module.sources_from_media_rows([{'webVideoUrl':'https://tiktok.com/@person/video/1234567890','text':'Missing chart setups while watching charts all day.','playCount':30000,'createTimeISO':'2026-11-06T00:00:00Z'}],'TikTok')[0]
 source.update(evaluation={'relevance':1},private_brief='Must never enter public storage')
 module.remember_public_sources([source])
 project=Project(name='Alerts',platform='iOS',status='unlaunched',description='Alerts traders about missing chart setups.',problem='Missing chart setups while away from the screen',category='finance')
 candidates=module.remembered_candidates(project)
 assert len(candidates)==1 and candidates[0]['metrics']['views']==30000
 assert 'evaluation' not in candidates[0] and 'private_brief' not in candidates[0]
 unrelated=project.model_copy(update={'description':'Track baby feeding and sleep routines.','problem':'Missing baby feeding records at night'})
 # Corpus retrieval prioritises recall, including lexical synonyms. Candidates
 # are never displayable without an independent project-specific verdict.
 from research_quality import select_results
 assert select_results(unrelated,module.remembered_candidates(unrelated),require_evaluation=True)[0]==[]
 with sqlite3.connect(tmp_path/'public.sqlite3') as db:db.execute('UPDATE public_sources SET created=?',(time.time()-22000,))
 assert len(module.remembered_candidates(project))==1


def test_semantic_cache_is_bound_to_full_brief_source_and_policy(monkeypatch,tmp_path):
 from app import Project
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'semantic.sqlite3'))
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 p=Project(name='Alerts',platform='iOS',status='unlaunched',description='An app that alerts traders about chart setups.',problem='Missing chart setups while away',category='finance')
 s={'id':'s1','title':'Missing setups while away','summary':'I need alerts when chart setups form.'}
 calls=[]
 def batch(project,sources):
  calls.append((project.problem,[x['summary'] for x in sources]))
  return {x['id']:{'provider':'gemini','intent':'creative_reference','relevance':.8} for x in sources}
 monkeypatch.setattr(module,'evaluate_batch',batch)
 assert module.evaluate(p,[s])['s1']['relevance']==.8
 assert module.evaluate(p,[s])['s1']['relevance']==.8
 assert len(calls)==1
 module.evaluate(p.model_copy(update={'problem':'Remembering baby feeding times'}),[s]);assert len(calls)==2
 module.evaluate(p,[{**s,'summary':'New original caption'}]);assert len(calls)==3
 monkeypatch.setattr(module,'EVALUATION_VERSION',999)
 module.evaluate(p,[s]);assert len(calls)==4


def test_unchanged_media_and_competitor_contracts_reuse_prior_verdicts_only(monkeypatch,tmp_path):
 monkeypatch.setattr(module,"EVALUATION_VERSION",14)  # Historical migration contract, before first-party policy 15.
 from app import Project
 import sqlite3,time
 path=tmp_path/'semantic.sqlite3'
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(path))
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 monkeypatch.setenv('OUTLOUD_GEMINI_MODEL','fixture-model')
 p=Project(name='Study',platform='iOS',status='unlaunched',description='Spaced repetition for difficult exams.',category='productivity')
 sources=[{'id':'video','title':'Exam preparation routine','summary':'My study routine','kind':'Video','platform':'TikTok'},
          {'id':'pitch','title':'A competing study app','summary':'Our app schedules exam revision','kind':'Post','platform':'X'},
          {'id':'need','title':'I need help revising','summary':'I keep forgetting my exam material','kind':'Post','platform':'X'},
          {'id':'ambiguous','title':'My revision routine','summary':'Been reviewing for too long','kind':'Post','platform':'X'}]
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE semantic_decisions(key TEXT PRIMARY KEY,data TEXT,created REAL)')
  for s,intent in zip(sources,['creative_reference','competitor','audience_problem','creative_reference']):
   db.execute('INSERT INTO semantic_decisions VALUES(?,?,?)',(module.evaluation_key(p,s,'fixture-model',policy=13),json.dumps({'id':s['id'],'provider':'gemini','policy_version':13,'intent':intent}),time.time()))
 checked=module.cached_evaluations(p,sources)
 assert {s['id'] for s in checked}=={'video','pitch'}
 assert all(s['evaluation']['policy_version']==13 and s['evaluation']['compatible_with_policy']==14 for s in checked)
 monkeypatch.setattr(module,'evaluate_batch',lambda *args:pytest.fail('Compatible saved verdicts must not trigger evaluation'))
 assert set(module.evaluate(p,sources[:2]))=={'video','pitch'}
 assert module.cached_evaluations(p.model_copy(update={'description':'An unrelated product.'}),sources)==[]
 assert module.cached_evaluations(p,[{**sources[0],'summary':'Changed caption'}])==[]


def test_semantic_batches_are_bounded_and_never_silently_drop_sources(monkeypatch,tmp_path):
 from app import Project
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'semantic.sqlite3'))
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 p=Project(name='Alerts',platform='iOS',status='unlaunched',description='An app that alerts traders about chart setups.',category='finance')
 sizes=[]
 def batch(project,sources):
  sizes.append(len(sources));return {x['id']:{'provider':'gemini','relevance':.8} for x in sources}
 monkeypatch.setattr(module,'evaluate_batch',batch)
 sources=[{'id':str(i),'title':'A source','summary':'Actual caption'} for i in range(11)]
 assert len(module.evaluate(p,sources))==11
 assert sorted(sizes)==[3,4,4]
 with pytest.raises(ValueError):module.evaluate(p,sources*3)


def test_prior_help_requests_require_literal_unresolved_quotes_and_current_routing(monkeypatch,tmp_path):
 monkeypatch.setattr(module,"EVALUATION_VERSION",14)  # Historical migration contract, before first-party policy 15.
 from app import Project
 import sqlite3,time
 path=tmp_path/'semantic.sqlite3'
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(path))
 monkeypatch.setenv('OUTLOUD_GEMINI_MODEL','fixture-model')
 p=Project(name='Study',platform='iOS',status='unlaunched',description='Exam revision scheduling for students.',category='productivity')
 quote='I need a way to remember my revision schedule.'
 base={'title':'Revision help','summary':quote,'kind':'Post','platform':'Reddit'}
 verdict={'provider':'gemini','policy_version':13,'intent':'audience_problem','need_status':'unresolved','relevance':.9,'request_quote':quote}
 cases=[('valid',{},{}),('invented',{}, {'request_quote':'Is there a tool for physics?'}),
        ('resolved',{}, {'need_status':'resolved'}),('weak',{}, {'relevance':.5}),
        ('pitch',{'summary':quote+' Try our app for exam revision.'},{}),
        ('rant',{'summary':'Been reviewing for too long.'},{'request_quote':'Been reviewing for too long.'})]
 sources=[]
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE semantic_decisions(key TEXT PRIMARY KEY,data TEXT,created REAL)')
  for ident,changes,decision in cases:
   s={**base,**changes,'id':ident};sources.append(s)
   db.execute('INSERT INTO semantic_decisions VALUES(?,?,?)',(module.evaluation_key(p,s,'fixture-model',policy=13),json.dumps({**verdict,**decision}),time.time()))
 checked=module.cached_evaluations(p,sources)
 assert [s['id'] for s in checked]==['valid']
 assert checked[0]['evaluation']['policy_version']==13


def test_provider_outage_preserves_verified_batches_but_never_accepts_failed_sources(monkeypatch,tmp_path):
 from app import Project
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'semantic.sqlite3'))
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 p=Project(name='Alerts',platform='iOS',status='unlaunched',description='An app that alerts traders about chart setups.',category='finance')
 sources=[{'id':str(i),'title':'A source','summary':'Actual caption'} for i in range(5)]
 calls=[]
 def batch(project,items):
  calls.append([x['id'] for x in items])
  if items[0]['id']=='4':raise httpx.HTTPStatusError('Unavailable',request=httpx.Request('POST','https://example.invalid'),response=httpx.Response(503))
  return {x['id']:{'provider':'gemini','relevance':.8} for x in items}
 monkeypatch.setattr(module,'evaluate_batch',batch)
 results=module.evaluate(p,sources)
 assert set(results)=={'0','1','2','3'} and results.unavailable_ids==['4']
 results=module.evaluate(p,sources)
 assert len(calls)==3  # Successful batch is reused; only one failed batch per request.
 assert results.unavailable_ids==['4']
 with pytest.raises(RuntimeError):module.evaluate(p,[sources[4]])


def test_media_and_audience_rubrics_are_evaluated_in_separate_batches(monkeypatch,tmp_path):
 from app import Project
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'semantic.sqlite3'))
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 p=Project(name='Alerts',platform='iOS',status='unlaunched',description='An app that alerts traders about chart setups.',category='finance')
 batches=[]
 def batch(project,sources):
  batches.append([module.visual_candidate(s) for s in sources])
  return {s['id']:{'provider':'gemini','relevance':.8} for s in sources}
 monkeypatch.setattr(module,'evaluate_batch',batch)
 module.evaluate(p,[{'id':'v','platform':'TikTok','title':'Staring at charts all day','summary':'Original caption'}, {'id':'r','platform':'Reddit','title':'Looking for chart alerts','summary':'An actual question'}])
 assert sorted(batches)==[[False],[True]]


def test_incomplete_verdict_batch_reports_each_missing_source(monkeypatch):
 from app import Project
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 p=Project(name='Study',platform='iOS',status='unlaunched',description='Help students remember their study material.',category='productivity')
 sources=[{'id':str(i),'title':'A study request','summary':'An actual request'} for i in range(4)]
 monkeypatch.setattr(module,'evaluate_batch',lambda project,items:{'0':{'provider':'gemini','relevance':.8}})
 result=module.evaluate(p,sources)
 assert list(result)==['0']
 assert set(result.unavailable_ids)=={'1','2','3'}
 assert result.failure_reasons==[{'type':'IncompleteVerdicts','status':None,'sources':3}]


def test_instagram_keywords_use_reels_and_bounded_individual_activity_phrase():
    from research_providers import instagram_keyword_input
    payload=instagram_keyword_input(['calorie tracking'],15)
    assert payload=={'hashtags':['calorie tracking'],'keywordSearch':True,'resultsType':'reels','resultsLimit':15}
    with pytest.raises(ValueError):instagram_keyword_input(['one','two'],15)
    with pytest.raises(ValueError):instagram_keyword_input(['calorie tracking'],True)


def test_explicit_negative_verdict_without_quote_is_cached_and_never_displayed(monkeypatch,tmp_path):
 from app import Project
 from research_quality import select_results
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'semantic.sqlite3'))
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 monkeypatch.setattr(module,'authorize',lambda *args:None)
 p=Project(name='Meals',platform='iOS',status='unlaunched',description='A photo calorie logger that makes recording meals faster.',problem='Slow meal logging',category='auto')
 source={'id':'unrelated','title':'Manual accounting data entry','summary':'I need help moving invoices into accounting software.','platform':'Reddit','kind':'Post'}
 calls=[]
 def respond(*args,**kwargs):
  calls.append(1)
  item={'id':'unrelated','relevance':0,'match_level':'Unrelated','intent':'irrelevant','evidence_quote':'','reason':'Different customer task.','need_status':'unclear','request_quote':'','competitor_name':'','competitor_job_quote':''}
  return httpx.Response(200,request=httpx.Request('POST','https://example.com'),json={'candidates':[{'content':{'parts':[{'text':json.dumps({'items':[item]})}]}}]})
 monkeypatch.setattr(module,'gemini_post',respond)
 for _ in range(2):
  decisions=module.evaluate(p,[source])
  assert decisions['unrelated']['intent']=='irrelevant'
  assert select_results(p,[{**source,'evaluation':decisions['unrelated']}],require_evaluation=True)[0]==[]
 assert len(calls)==1


def test_evaluation_reuses_alternate_model_verdict_after_overload(monkeypatch,tmp_path):
 from app import Project
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'semantic.sqlite3'))
 monkeypatch.setenv('GEMINI_API_KEY','test-placeholder')
 monkeypatch.setenv('OUTLOUD_GEMINI_MODEL','primary')
 monkeypatch.setenv('OUTLOUD_GEMINI_FALLBACK_MODEL','alternate')
 attempts=[];reservations=[]
 monkeypatch.setattr(module,'authorize',lambda *args:reservations.append(args))
 project=Project(name='Meals',platform='iOS',status='unlaunched',description='A photo calorie logger that makes recording meals faster.',category='auto')
 source={'id':'other','title':'Import invoices','summary':'How can I import older invoices?', 'platform':'Reddit','kind':'Post'}
 def respond(url,**kwargs):
  attempts.append(url.rsplit('/',1)[-1])
  request=httpx.Request('POST',url)
  if attempts[-1]=='primary:generateContent':
   return httpx.Response(503,request=request)
  item={'id':'other','intent':'irrelevant','relevance':0}
  return httpx.Response(200,request=request,json={'candidates':[{'content':{'parts':[{'text':json.dumps({'items':[item]})}]}}]})
 monkeypatch.setattr(module,'gemini_post',respond)
 assert module.evaluate(project,[source])['other']['model']=='alternate'
 assert module.evaluate(project,[source])['other']['model']=='alternate'
 assert attempts==['primary:generateContent','alternate:generateContent']
 assert reservations==[('gemini',10000),('gemini',10000)]
