from datetime import datetime,timezone
from app import Project
from research_readiness import assess,timestamp


def test_empty_or_catalog_workspace_cannot_pass_paid_targets():
    p=Project(name='Test',platform='Web',status='unlaunched',category='other',description='A software product for a real customer problem.')
    r=assess(p,{'discover':[{'title':'catalog example','url':'https://example.com'}],'conversations':[]})
    assert not r['target_volume_met'] and r['capacity_supports_target']
    assert r['target_total']==60
    assert [r['lanes'][lane]['target'] for lane in ('discover','competitors','conversations')]==[15,15,30]
    assert all(v['checked_matches']==0 for v in r['lanes'].values())
    assert r['conversation_targets']['X']['shortfall']==15
    assert 'Not verified' in r['source_availability']


def test_dates_must_be_timezone_aware():
    assert timestamp('2026-11-08T00:00:00') is None
    assert timestamp('not a date') is None
    assert timestamp('2026-11-08T00:00:00Z')==datetime(2026,11,8,tzinfo=timezone.utc).timestamp()
