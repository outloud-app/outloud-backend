import pytest
import native_conversations as native


def test_limits_and_original_dates():
    with pytest.raises(ValueError):native.search_input('calories',21)
    with pytest.raises(ValueError):native.search_input('calories',True)
    row={'url':'https://x.com/example/status/1234567890123456789','text':'I keep forgetting to log meals. Is there an easier way?',
         'created_at':'Fri Nov 06 12:00:00 +0000 2026','author':{'screen_name':'example'},'favorite_count':2,'view_count':True}
    source=native.normalize([row])[0]
    assert source['published_at']=='2026-11-06T12:00:00+00:00'
    assert source['summary']==row['text']
    assert source['metrics']['likes']==2
    assert 'views' not in source['metrics']
    assert 'evaluation' not in source
    assert native.normalize([{**row,'created_at':'unknown'}])==[]


def test_cached_native_results_do_not_spend_or_require_start_permission(tmp_path,monkeypatch):
    import json,sqlite3,hashlib
    payload=native.search_input('calorie tracking')
    key='native-x-v1:'+hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    path=tmp_path/'provider.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE media_jobs(key TEXT PRIMARY KEY,run TEXT,rows TEXT,created REAL)')
        db.execute('INSERT INTO media_jobs VALUES(?,?,?,0)',(key,'{}','[]'))
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(path))
    monkeypatch.delenv('OUTLOUD_CONVERSATION_START_ALLOWED',raising=False)
    monkeypatch.setattr(native,'authorize',lambda *a:pytest.fail('Cached results must not spend'))
    assert native.discover('calorie tracking')==[]


def test_collection_is_disabled_by_default(tmp_path,monkeypatch):
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'provider.sqlite3'))
    monkeypatch.delenv('OUTLOUD_CONVERSATION_START_ALLOWED',raising=False)
    with pytest.raises(native.ProviderNotConfigured):native.discover('calorie tracking')


def test_reddit_body_is_separate_and_missing_counts_are_not_invented():
    row={'url':'https://www.reddit.com/r/loseit/comments/abc123/help/',
         'title':'Calorie logging is exhausting','selftext':'Is there an easier way to log my meals every day?',
         'created_utc':1793966400,'author':'someone'}
    source=native.normalize([row],'Reddit')[0]
    assert source['title']==row['title']
    assert source['summary']==row['selftext']
    assert 'score' not in source['metrics']
    assert not source['evidence']['engagement_verified']
    assert native.search_input('calorie tracking',platform='Reddit')['timeframe']=='month'


def test_query_compiler_groups_phrases_and_rejects_operators():
    query=native.compile_query(['unpaid invoice','late payments'],'X')
    assert query.startswith('((unpaid invoice) OR (late payments)) (')
    assert native.compile_query(['flashcards','revision schedule'],'Reddit').startswith('((flashcards) OR (revision AND schedule)) AND (help OR')
    for phrases in (['study OR games','flashcards'],['same','same'],['site:evil.com','study'],['a "quote"','study'],['market -crypto','chart alerts']):
        with pytest.raises(ValueError):native.compile_query(phrases,'X')


def test_provider_quota_error_is_not_an_empty_search_and_blocks_new_queries(tmp_path,monkeypatch):
    import sqlite3,json,time
    path=tmp_path/'media.sqlite3'
    rows=[{'status':'error','error_kind':'free_tier_limit','reason':'Private provider details'}]
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE media_jobs(key TEXT PRIMARY KEY,run TEXT,rows TEXT,created REAL)')
        db.execute('INSERT INTO media_jobs VALUES(?,?,?,?)',('native-x-v1:old-query','{}',json.dumps(rows),time.time()))
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(path))
    monkeypatch.setenv('OUTLOUD_CONVERSATION_START_ALLOWED','1')
    monkeypatch.setattr(native,'authorize',lambda *a:pytest.fail('Exhausted quota must not spend again'))
    with pytest.raises(native.ConversationUnavailable,match='quota is exhausted'):
        native.discover('a different product')
    # Planning must also stop before reserving Gemini spend for a search that
    # the account-level provider quota cannot execute.
    with pytest.raises(native.ConversationUnavailable,match='quota is exhausted'):
        native.query_for(object(),'X')
    with pytest.raises(native.ConversationUnavailable,match='not an empty search'):
        native.check_collection([{'status':'error','reason':'sensitive details'}],'Reddit')
    native.check_collection([],'X')


def test_old_quota_failure_does_not_block_next_month(tmp_path,monkeypatch):
    import sqlite3,json
    path=tmp_path/'media.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE media_jobs(key TEXT PRIMARY KEY,run TEXT,rows TEXT,created REAL)')
        db.execute('INSERT INTO media_jobs VALUES(?,?,?,0)',('native-x-v1:old-query','{}',json.dumps([{'status':'error','error_kind':'free_tier_limit'}])))
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(path))
    monkeypatch.delenv('OUTLOUD_CONVERSATION_START_ALLOWED',raising=False)
    with pytest.raises(native.ProviderNotConfigured):native.discover('a different product')


def test_alternative_x_search_is_bounded_and_omits_contact_enrichment(monkeypatch):
    monkeypatch.setenv('OUTLOUD_X_COLLECTOR','raven')
    payload=native.search_input('("unpaid invoice" OR "late payments")',20)
    assert payload['targets']==['("unpaid invoice" OR "late payments")']
    assert payload['maxItems']==20 and payload['searchType']=='latest'
    assert payload['findEmails'] is False and payload['includeAbout'] is False
    assert payload['excludeReposts'] is True
    assert native.collector('X')==('pro100chok~x-twitter-all-in-one-scraper','native-x-raven-v1:',.01)
    with pytest.raises(ValueError):native.search_input('invoice',21)


def test_alternative_x_normalizes_original_dates_and_counts():
    row={'url':'https://x.com/someone/status/1234567890123456789','text':'How do you follow up when clients ignore an unpaid invoice?',
         'createdAt':'2026-11-07T12:00:00Z','author':{'username':'someone'},'viewCount':240,'likeCount':3,'replyCount':2}
    item=native.normalize([row])[0]
    assert item['author']=='someone' and item['published_at']=='2026-11-07T12:00:00+00:00'
    assert item['metrics']['views']==240 and item['metrics']['likes']==3
    assert item['metrics']['comments']==2
    assert native.normalize([{**row,'createdAt':'2026-11-07T12:00:00'}])==[]


def test_one_collector_quota_does_not_block_an_independent_collector(tmp_path,monkeypatch):
    import sqlite3,json,time
    path=tmp_path/'media.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE media_jobs(key TEXT PRIMARY KEY,run TEXT,rows TEXT,created REAL)')
        db.execute('INSERT INTO media_jobs VALUES(?,?,?,?)',('native-x-v1:quota','{}',json.dumps([{'status':'error','error_kind':'free_tier_limit'}]),time.time()))
        monkeypatch.setenv('OUTLOUD_X_COLLECTOR','raven')
        native.check_recent_quota(db,'X')
        monkeypatch.setenv('OUTLOUD_X_COLLECTOR','atomus')
        with pytest.raises(native.ConversationUnavailable):native.check_recent_quota(db,'X')

@pytest.mark.parametrize('groups',[
    [['meal logging','calorie tracking'],['food diary','logging meals'],['counting calories','tracking food']],
    [['unpaid invoices','late payments'],['chasing clients','invoice reminders'],['freelance billing','payment followups']],
    [['exam revision','study schedule'],['flashcard reviews','remembering material'],['spaced repetition','revision planning']],
])
def test_diverse_problem_plans_produce_three_independent_bounded_queries(groups):
    plan=native.compile_plan(groups,'X')
    assert len(set(plan))==3
    assert all(len(query)<600 for query in plan)
    assert all(native.search_input(query)['maxItems']==20 for query in plan)
    with pytest.raises(ValueError):native.compile_plan([groups[0],groups[0],groups[2]],'X')


def test_cached_three_query_plan_does_not_spend(tmp_path,monkeypatch):
    import research_retrieval
    plan=native.compile_plan([['meal logging','calorie tracking'],['food diary','logging meals'],['counting calories','tracking food']],'X')
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'provider.sqlite3'))
    monkeypatch.setattr(research_retrieval,'cached_model',lambda p:{'native_x_query_plan':plan,'native_x_query_plan_policy':native.QUERY_POLICY,'native_x_query_plan_plan_policy':native.PLAN_POLICY})
    monkeypatch.setattr(native,'authorize',lambda *args:pytest.fail('A saved plan must not spend'))
    assert native.queries_for(object())==plan


def test_generic_friction_is_constrained_by_customer_activity(monkeypatch):
    monkeypatch.setenv('OUTLOUD_X_COLLECTOR','raven')
    groups=[['meal logging','calorie tracking'],['manual data entry','app fatigue'],['food diary','counting macros']]
    queries=native.compile_plan(groups,'Reddit')
    assert queries[1].startswith('((manual AND data AND entry) OR (app AND fatigue)) AND (help OR')
    assert queries[1].endswith('AND ("meal" OR "calorie")')
    assert queries[2].endswith('AND ("meal" OR "calorie")')
    assert queries[0].startswith('((meal AND logging) OR (calorie AND tracking)) AND (help OR')
    study=native.compile_plan([['exam revision','study schedule'],['screen fatigue','time pressure'],['flashcard reviews','remembering material']],'X')
    assert study==['exam revision','screen fatigue exam','flashcard reviews exam']
    assert 'meal' not in study[1]


def test_x_does_not_emit_literal_and_or_exact_activity_phrases(monkeypatch):
    monkeypatch.setenv('OUTLOUD_X_COLLECTOR','raven')
    groups=[['food logging','counting calories'],['manual entries','meal tracking'],['nutrition diary','diet apps']]
    plan=native.compile_plan(groups,'X')
    assert all(' AND ' not in query for query in plan)
    assert plan==['food logging','manual entries food','nutrition diary food']
    assert '"food logging"' not in plan[0]
    assert all(' OR ' not in query and '(' not in query for query in plan)


def test_compiler_upgrade_reuses_saved_activity_groups_without_model_call(tmp_path,monkeypatch):
    monkeypatch.setenv('OUTLOUD_X_COLLECTOR','raven')
    import research_retrieval
    groups=[['food logging','counting calories'],['manual meal entries','tedious food tracking'],['nutrition diary','diet apps']]
    model={'native_x_query_plan_groups':groups,'native_x_query_plan_plan_policy':native.PLAN_POLICY,
           'native_x_query_plan_policy':native.QUERY_POLICY-1,'unrelated_profile':'preserved'}
    saved=[]
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'provider.sqlite3'))
    monkeypatch.setattr(research_retrieval,'cached_model',lambda p:model)
    monkeypatch.setattr(research_retrieval,'save_model',lambda p,value:saved.append(value))
    monkeypatch.setattr(native,'authorize',lambda *args:pytest.fail('Recompiling a saved plan must not spend'))
    assert native.queries_for(object())==['food logging','manual meal entries food','nutrition diary food']
    assert saved[0]['unrelated_profile']=='preserved'
    assert saved[0]['native_x_query_plan_policy']==native.QUERY_POLICY


def test_supported_x_adapter_keeps_native_intent_operators(monkeypatch):
    monkeypatch.setenv('OUTLOUD_X_COLLECTOR','atomus')
    plan=native.compile_plan([['meal logging','calorie tracking'],['manual food entries','tedious meal search'],['food diary','counting macros']],'X')
    assert '(struggling OR frustrating OR' in plan[0]
    assert ' OR ' in plan[0] and ' AND ' not in plan[0]
    assert 'since' in native.search_input(plan[0])


def test_provider_error_rows_are_not_reported_as_empty_search():
    with pytest.raises(native.ConversationUnavailable):
        native.check_collection([{'_type':'error','message':'failed target'},{'_type':'summary'}],'Reddit')


def test_current_reddit_adapter_bounds_search_and_preserves_title_only_questions(monkeypatch):
    monkeypatch.setenv('OUTLOUD_REDDIT_COLLECTOR','harshmaur')
    payload=native.search_input('journaling help',platform='Reddit')
    assert payload['postedAfter']=='30 days' and payload['maxPostsCount']==20
    assert payload['searchComments'] is False and payload['crawlCommentsPerPost'] is False
    assert native.collector('Reddit')[2]==.10
    row={'dataType':'post','postUrl':'https://www.reddit.com/r/journaling/comments/abc123/question/',
         'title':'Can anyone recommend a journal app with writing prompts?', 'body':'',
         'createdAt':'2026-11-20T08:00:00Z','authorName':'real_author','upVotes':4,'commentsCount':2}
    result=native.normalize([row],'Reddit')[0]
    assert result['summary']==row['title'] and result['author']=='real_author'
    assert result['metrics']['score']==4 and result['metrics']['comments']==2
    assert native.normalize([{**row,'dataType':'community'}],'Reddit')==[]


def test_grounded_activities_drive_distinct_queries_without_paid_planning(monkeypatch):
    from app import Project
    import research_retrieval
    project=Project(name='Meal Diary',platform='iOS',status='launched',category='other',
        description='Track calorie intake, estimate portion size, and record meals in a food diary.',
        keywords=['habit tracker','calorie intake','portion size'])
    monkeypatch.setattr(research_retrieval,'cached_model',lambda p:{'adjacent_topics':['food diary','home workouts']})
    monkeypatch.setattr(native,'authorize',lambda *args:pytest.fail('Grounded phrases need no paid planning'))
    assert native.queries_for(project,'Reddit')==['calorie intake','portion size','food diary']


def test_query_yield_counts_only_checked_verdicts_and_delivered_conversations():
    queries=[{'query':'food diary','platform':'Reddit','returned':4,'status':'completed',
              'source_ids':['hit','off_topic','unchecked','publisher']}]
    checked=[{'id':'off_topic','evaluation':{'intent':'irrelevant'}}]
    selected=[{'id':'hit','intent':'conversations'},{'id':'publisher','intent':'competitors'}]
    assert native.query_yield(queries,checked,selected)==[
        {'query':'food diary','platform':'Reddit','returned':4,'irrelevant':1,'accepted':1,'status':'completed'}]


def test_scoped_reddit_queries_use_provider_community_filter(monkeypatch):
    monkeypatch.setenv('OUTLOUD_REDDIT_COLLECTOR','harshmaur')
    payload=native.search_input('subreddit:MealPrep self:true "meal logging"',platform='Reddit')
    assert payload['withinCommunity']=='MealPrep'
    assert payload['searchTerms']==['self:true "meal logging"']
    assert payload['searchSort']=='relevance' and payload['searchTime']=='month'


def test_quota_failure_from_replaced_credential_does_not_stop_new_account(tmp_path, monkeypatch):
    import json
    import sqlite3
    import time

    monkeypatch.setenv('APIFY_TOKEN', 'old-test-credential')
    old_fingerprint = native.credential_fingerprint()
    with sqlite3.connect(tmp_path / 'provider.sqlite3') as db:
        db.execute('CREATE TABLE media_jobs(key TEXT PRIMARY KEY,run TEXT,rows TEXT,created REAL)')
        db.execute('INSERT INTO media_jobs VALUES(?,?,?,?)', (
            native.collector('X')[1] + 'prior', json.dumps({'credential_fingerprint': old_fingerprint}),
            json.dumps([{'status': 'error', 'error_kind': 'free_tier_limit'}]), time.time()))
        with pytest.raises(native.ConversationUnavailable, match='quota is exhausted'):
            native.check_recent_quota(db, 'X')
        monkeypatch.setenv('APIFY_TOKEN', 'replacement-test-credential')
        native.check_recent_quota(db, 'X')


def test_apidojo_search_stays_bounded_and_uses_native_date_filter(monkeypatch):
    monkeypatch.setenv('OUTLOUD_X_COLLECTOR', 'apidojo')
    payload = native.search_input('repair broken alerts', 20)
    assert payload['maxItems'] == 20
    assert payload['sort'] == 'Top'
    assert payload['searchTerms'][0].startswith('repair broken alerts since:')


def test_actor_start_retries_only_a_confirmed_concurrency_rejection(monkeypatch):
    import httpx
    import native_access

    url = 'https://api.apify.com/v2/acts/test/runs'
    request = httpx.Request('POST', url)
    busy = httpx.Response(402, request=request, json={'error': {'type': 'concurrent-runs-limit-exceeded'}})
    started = httpx.Response(201, request=request, json={'data': {'id': 'test'}})
    responses = iter([busy, started])
    delays = []
    monkeypatch.setattr(native_access.time, 'sleep', delays.append)
    assert native_access.actor_start(lambda *_: next(responses), url) == {'id': 'test'}
    assert delays == [2]
    payment_required = httpx.Response(402, request=request, json={'error': {'type': 'payment-required'}})
    with pytest.raises(httpx.HTTPStatusError):
        native_access.actor_start(lambda *_: payment_required, url)
    assert delays == [2]


def test_native_reply_collection_requires_thread_membership_and_keeps_reply_evidence(monkeypatch):
    root_url = 'https://x.com/ideas/status/12345/'
    base = {'createdAt': '2026-11-20T12:00:00Z', 'author': {'username': 'tester'}}
    rows = [
        {**base, 'id': '12345', 'url': root_url, 'text': 'Can a scanner run on multiple charts?'},
        {**base, 'id': '12346', 'url': 'https://x.com/tester/status/12346/', 'isReply': True,
         'conversationId': '12345', 'text': 'Does the scanner support price alerts that work on mobile?'},
        {**base, 'id': '12347', 'url': 'https://x.com/tester/status/12347/', 'isReply': True,
         'conversationId': '99999', 'text': 'This reply belongs to an unrelated thread.'},
    ]
    def cached(key, path, start, **kwargs):
        assert key.startswith('native-x-raven-thread-v1:')
        return {}, rows, 0
    monkeypatch.setattr(native, 'cached_collection', cached)
    import research_providers
    monkeypatch.setattr(research_providers, 'remember_public_sources', lambda sources: None)

    [reply] = native.discover_replies(root_url)
    assert reply['url'] == rows[1]['url']
    assert reply['summary'] == rows[1]['text']
    assert reply['thread_context'] == {'url': root_url, 'text': rows[0]['text']}
    with pytest.raises(ValueError):
        native.discover_replies('https://example.org/ideas/status/12345/')


def test_xquik_uses_a_deeper_bounded_native_search(monkeypatch):
    monkeypatch.setenv('OUTLOUD_X_COLLECTOR', 'xquik')
    payload = native.search_input('calorie logging app workflow', 60)
    assert payload['maxItems'] == 60
    assert payload['twitterContent'].startswith('calorie logging app workflow since:')
    with pytest.raises(ValueError):
        native.search_input('calorie logging app workflow', 61)
    with pytest.raises(ValueError):
        native.search_input('calorie logging app workflow', 60, 'Reddit')
