from demo_access import demo_results


def test_real_matches_are_capped_per_lane_and_secrets_are_removed():
    def sources(section, competitor=False):
        return [dict(id=f'{section}-{competitor}-{i}', section=section,
                     competitor=competitor, platform='Reddit', kind='Text',
                     title='Private title', url='https://reddit.com/private',
                     summary='Private body', analysis={'private': True}) for i in range(5)]
    original = {'discover': sources('discover') + sources('discover', True),
                'conversations': sources('conversations')}
    public = demo_results(original)
    assert public['preview']['locked_count'] == 6
    assert len(public['discover']) == 10
    for source in public['discover'] + public['conversations']:
        if source.get('locked'):
            assert source['url'] == '' and source['summary'] == ''
            assert 'analysis' not in source
    assert original['discover'][4]['url'] == 'https://reddit.com/private'


def test_does_not_invent_extra_results():
    assert demo_results({'discover': [], 'conversations': []})['preview']['locked_count'] == 0


def test_public_preview_never_exposes_internal_source_audit():
 from demo_access import demo_results
 result=demo_results({'discover':[],'conversations':[],'quality_report':{'rejected':[{'evaluation':{'evidence_quote':'Internal candidate quotation'}}]}})
 assert 'quality_report' not in result


def test_visible_preview_diversifies_platforms_before_filling_spaces():
    sources=[dict(id=str(i),platform=platform,kind='Text',title='Original title',summary='Original body',url='https://example.com',competitor=False)
             for i,platform in enumerate(['TikTok','TikTok','TikTok','Instagram','Reddit','X','TikTok'])]
    result=demo_results({'discover':sources,'conversations':[]})
    shown=[s for s in result['discover'] if not s.get('locked')]
    assert [s['platform'] for s in shown]==['TikTok','Instagram','Reddit','X']
    hidden=[s for s in result['discover'] if s.get('locked')]
    assert len(hidden)==3
    assert hidden[0]['teaser']['title']=='Original title'
    assert hidden[0]['teaser']['summary']=='Original body'
    assert hidden[0]['url']=='' and 'analysis' not in hidden[0]


def test_teasers_use_real_image_without_exposing_video_or_full_body():
    sources=[dict(id=str(i),platform='TikTok',kind='Video',title='Actual title',summary='a'*1000,author='Actual creator',url='https://tiktok.com/video/123',competitor=False,
                  media={'type':'video','url':'https://example.com/private.mp4','poster':'https://example.com/poster.jpg'}) for i in range(5)]
    result=demo_results({'discover':sources,'conversations':[]})
    teaser=result['discover'][3]['teaser']
    assert teaser['media']=={'type':'image','url':'https://example.com/poster.jpg'}
    assert len(teaser['summary'])==420
    assert 'private.mp4' not in str(result['discover'][3])
