import pytest
from datetime import datetime, timezone
import native_conversations as native
import research_providers as providers
import research_quality as quality
from conversation_fill import fill


def test_paused_collection_does_not_spend_or_change_existing_results(monkeypatch):
    monkeypatch.setenv('OUTLOUD_CONVERSATION_START_ALLOWED','0')
    monkeypatch.setattr(native,'discover',lambda *a:pytest.fail('No acquisition allowed'))
    selected=[{'id':'existing'}];report={'accepted':1}
    assert fill(object(),selected,report)==(selected,report,[],[])


def test_only_deficient_network_gets_remaining_distinct_queries_and_accepted_content_survives(monkeypatch):
    monkeypatch.setenv('OUTLOUD_CONVERSATION_START_ALLOWED','1')
    existing=[{'id':str(i),'platform':'X','intent':'conversations','section':'conversations',
               'published_at':datetime.now(timezone.utc).isoformat()} for i in range(8)]
    calls=[]
    monkeypatch.setattr(native,'queries_for',lambda p,n:['first','second','third'])
    monkeypatch.setattr(native,'discover',lambda q,l,w,n:calls.append((n,q)) or [])
    result,_,collection,_=fill(object(),existing,{'rejected':[]})
    assert result==existing and calls==[('Reddit','second'),('Reddit','third')]
    assert collection[0]['phase']=='fill'


def test_failed_expansion_keeps_checked_cards_and_does_not_repeat_request(monkeypatch):
    monkeypatch.setenv('OUTLOUD_CONVERSATION_START_ALLOWED','1')
    calls=[]
    monkeypatch.setattr(native,'queries_for',lambda p,n:['first','second','third'])
    def fail(q,*args):
        calls.append(q)
        raise providers.BudgetExceeded('private diagnostic')
    monkeypatch.setattr(native,'discover',fail)
    selected=[{'id':'old','platform':'TikTok','intent':'discover'}]
    result,_,collection,issues=fill(object(),selected,{'rejected':[]})
    assert result==selected and calls==['second','second']
    assert len(collection)==2 and all(c['status']=='unavailable' for c in collection)
    assert 'private' not in str(issues)
