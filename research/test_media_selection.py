from research_providers import media_candidates


def candidate(identifier, platform='TikTok', intent='creative_reference', score=.8):
    text='A real post about the customer routine and problem.'
    return {'id':identifier,'platform':platform,'title':text,'summary':text,
            'evaluation':{'intent':intent,'relevance':score,'evidence_quote':text}}


def test_irrelevant_and_unverified_posts_cannot_consume_media_collection():
    unrelated=candidate('unrelated', intent='irrelevant')
    unsupported=candidate('unsupported');unsupported['evaluation']['evidence_quote']='A made up source quote'
    missing=candidate('missing');missing.pop('evaluation')
    good=candidate('good')
    assert media_candidates([unrelated,unsupported,missing,good]) == [good]


def test_media_collection_has_bounded_room_for_both_lanes_and_platforms():
    sources=[candidate(f'{platform}-{intent}-{i}',platform,intent)
             for platform in ('Instagram','TikTok')
             for intent in ('creative_reference','competitor') for i in range(10)]
    selected=media_candidates(sources)
    assert len(selected)==12
    for platform in ('Instagram','TikTok'):
        for intent in ('creative_reference','competitor'):
            assert sum(s['platform']==platform and s['evaluation']['intent']==intent for s in selected)==3


def test_native_search_reuses_pending_and_completed_run(monkeypatch,tmp_path):
    import research_providers as provider
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'media.sqlite3'))
    starts=[];polls=[]
    monkeypatch.setattr(provider,'start_tiktok_discovery',lambda *args:starts.append(args) or {'run_id':'fixture','dataset_id':'fixture','platform':'TikTok'})
    def collect(run):
        polls.append(run)
        if len(polls)==1:raise provider.MediaPending()
        return [{'webVideoUrl':'https://www.tiktok.com/@creator/video/1234567890',
                 'text':'A real customer explains the frustration of tracking meals every day.',
                 'playCount':15000,'diggCount':900,'createTimeISO':'2026-11-06T12:00:00Z',
                 'authorMeta':{'name':'creator'},'videoMeta':{'coverUrl':'https://p16.tiktokcdn.com/cover.jpg'}}]
    monkeypatch.setattr(provider,'collect_media_run',collect)
    import pytest
    phrases=['tracking meals every day','photo calorie tracking app']
    with pytest.raises(provider.MediaPending):provider.discover_native_media(phrases)
    result=provider.discover_native_media(phrases)
    again=provider.discover_native_media(phrases)
    assert len(starts)==1 and len(polls)==2
    assert result[0]['metrics']['views']==15000
    assert again[0]['metrics']['checked_at']==result[0]['metrics']['checked_at']


def test_native_search_cannot_spend_when_collection_is_disabled(monkeypatch,tmp_path):
    import research_providers as provider
    import pytest
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'media.sqlite3'))
    monkeypatch.setenv('OUTLOUD_MEDIA_SEARCH_ALLOWED','0')
    monkeypatch.setattr(provider,'authorize',lambda *args:pytest.fail('No spend reservation without authorization'))
    with pytest.raises(provider.ProviderNotConfigured):
        provider.discover_native_media(['meal tracking frustration'])


def test_instagram_search_pins_one_exact_topic_and_bounds_results():
    import pytest
    from research_providers import instagram_discovery_input
    payload=instagram_discovery_input(['#foodtracker'],15)
    assert payload['directUrls']==['https://www.instagram.com/explore/tags/foodtracker/']
    assert payload['resultsLimit']==15 and payload['onlyPostsNewerThan']=='90 days'
    for tags,limit in [(['#foodtracker','#fitness'],15),(['https://example.com'],15),(['#x/y'],15),(['#foodtracker'],True),(['#foodtracker'],100)]:
        with pytest.raises(ValueError):instagram_discovery_input(tags,limit)


def test_instagram_native_jobs_reuse_without_collection_permission(monkeypatch,tmp_path):
    import research_providers as provider
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'media.sqlite3'))
    starts=[]
    monkeypatch.setattr(provider,'start_instagram_discovery',lambda *args:starts.append(args) or {'run_id':'ig','dataset_id':'data','platform':'Instagram'})
    monkeypatch.setattr(provider,'collect_media_run',lambda run:[{'url':'https://www.instagram.com/p/AbC123/',
        'caption':'Logging meals should not take your whole evening.', 'likesCount':2000,
        'timestamp':'2026-11-06T12:00:00Z','displayUrl':'https://scontent.cdninstagram.com/post.jpg'}])
    first=provider.discover_native_media(['#foodtracker'],platform='Instagram')
    monkeypatch.setattr(provider,'start_instagram_discovery',lambda *args:(_ for _ in ()).throw(AssertionError('Do not start twice')))
    monkeypatch.setenv('OUTLOUD_MEDIA_START_ALLOWED','0')
    again=provider.discover_native_media(['#foodtracker'],platform='Instagram')
    assert len(starts)==1 and len(first)==1
    assert again[0]['metrics']['likes']==2000
    assert again[0]['metrics']['checked_at']==first[0]['metrics']['checked_at']
