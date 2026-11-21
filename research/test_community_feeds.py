from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape
import httpx
import pytest
import community_feeds as feeds
from app import Project
from live_discovery import semantic_search_plan, fresh_query


def entry(published=None, updated=None):
 now=datetime.now(timezone.utc)
 return '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Any way to stop wasting groceries?</title><link href="https://www.reddit.com/r/MealPrepSunday/comments/abc123/groceries/"/><published>'+str(published or now.isoformat())+'</published><updated>'+str(updated or now.isoformat())+'</updated><author><name>/u/reader</name></author><category term="MealPrepSunday"/><content type="html">'+escape('<p>I keep buying food that goes bad before I use it. Is there an app to plan around what I already have?</p> submitted by /u/reader [link] [comments]')+'</content></entry></feed>'


def test_feed_preserves_original_need_and_date_without_controls_or_fake_metrics():
 source=feeds.parse_feed(entry())[0]
 assert source['summary'].startswith('I keep buying food')
 assert 'submitted by' not in source['summary']
 assert source['community']=='r/MealPrepSunday'
 assert source['evidence']['provider']=='reddit_public_feed'
 assert 'metrics' not in source


def test_old_post_edit_does_not_make_a_current_conversation():
 now=datetime.now(timezone.utc)
 assert feeds.parse_feed(entry((now-timedelta(days=90)).isoformat(),now.isoformat()))==[]


def test_feed_rejects_xml_entities():
 with pytest.raises(ValueError):feeds.parse_feed('<!DOCTYPE foo [<!ENTITY a "x">]><feed/>')


def test_feed_cache_avoids_duplicate_provider_requests(monkeypatch):
 monkeypatch.setattr(feeds,'_cache',{})
 monkeypatch.setattr(feeds,'_retry_after',0)
 calls=[]
 def get(url,**kwargs):
  calls.append(url)
  return httpx.Response(200,text=entry(),request=httpx.Request('GET',url))
 monkeypatch.setattr(feeds.httpx,'get',get)
 assert feeds.fetch_recent('MealPrepSunday')
 assert feeds.fetch_recent('mealprepsunday')
 assert len(calls)==1


def test_rate_limit_is_respected_across_communities(monkeypatch):
 monkeypatch.setattr(feeds,'_cache',{})
 monkeypatch.setattr(feeds,'_retry_after',0)
 calls=[]
 def get(url,**kwargs):
  calls.append(url)
  return httpx.Response(429,headers={'retry-after':'120'},request=httpx.Request('GET',url))
 monkeypatch.setattr(feeds.httpx,'get',get)
 for community in ('MealPrepSunday','productivity'):
  # A separate collector process has no in-memory backoff; the database still protects it.
  monkeypatch.setattr(feeds,'_retry_after',0)
  with pytest.raises(feeds.FeedUnavailable):feeds.fetch_recent(community)
 assert len(calls)==1


def test_fresh_acquisition_replaces_search_slots_instead_of_expanding_budget():
 p=Project(name='PantryMate',platform='Web',status='unlaunched',category='other',description='Meal planning with groceries already at home.')
 brief={'conversations':['help finding meal ideas']*18,'for_you':['meal preparation inspiration']*6,'competitors':['pantry meal planning app']*6,'subreddits':['MealPrepSunday','Cooking','EatCheapAndHealthy']}
 native=semantic_search_plan(p,brief,community_feeds=True)
 indexed=semantic_search_plan(p,brief,community_feeds=False)
 assert len(native)==len(indexed)<=24
 assert sum(query.startswith('community-feed:') for _,query in native)==3
 assert all('after:' in fresh_query(platform,query) for platform,query in indexed)
