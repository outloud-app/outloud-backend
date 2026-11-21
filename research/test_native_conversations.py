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
    assert native.search_input('calorie tracking',platform='Reddit')['timeframe']=='week'


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
    assert payload['postedAfter']=='7 days' and payload['maxPostsCount']==20
    assert payload['searchComments'] is False and payload['crawlCommentsPerPost'] is False
    assert native.collector('Reddit')[2]==.10
    row={'dataType':'post','postUrl':'https://www.reddit.com/r/journaling/comments/abc123/question/',
         'title':'Can anyone recommend a journal app with writing prompts?', 'body':'',
         'createdAt':'2026-11-20T08:00:00Z','authorName':'real_author','upVotes':4,'commentsCount':2}
    result=native.normalize([row],'Reddit')[0]
    assert result['summary']==row['title'] and result['author']=='real_author'
    assert result['metrics']['score']==4 and result['metrics']['comments']==2
    assert native.normalize([{**row,'dataType':'community'}],'Reddit')==[]


def test_short_user_keywords_drive_native_queries_without_paid_planning(monkeypatch):
    from app import Project
    p=Project(name='Calorie diary',platform='iOS',status='launched',category='other',
        description='Record meals and track calorie intake with a daily food diary.',keywords=['habit tracker','calorie diary'])
    monkeypatch.setattr(native,'authorize',lambda *a:pytest.fail('User-grounded search should not pay for another wording plan'))
    assert native.queries_for(p,'Reddit')==['calorie diary help','calorie diary recommendation','calorie diary app']



def test_named_competitor_guides_distinct_conversation_search(monkeypatch):
    from app import Project
    project = Project(name='Invoice desk', platform='Web', status='launched', category='other',
                      description='Manage invoice reminders for freelancers and track late payments.',
                      keywords=['invoice reminders'], competitors=['Ledger Desk, Invoice Helper'])
    monkeypatch.setattr(native, 'authorize', lambda *args: pytest.fail('No paid planning needed'))
    assert native.queries_for(project, 'Reddit') == [
        'invoice reminders help', 'Ledger Desk alternative', 'invoice reminders app'
    ]
