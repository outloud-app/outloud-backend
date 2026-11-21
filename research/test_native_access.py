import pytest,httpx
import native_access
import research_providers

require_native_access = native_access.require


def test_rejected_credential_is_not_treated_as_an_empty_search():
 class Client:
  def get(self,*args,**kwargs):return httpx.Response(401)
 with pytest.raises(native_access.NativeAccessUnavailable,match='credential was rejected'):
  native_access.check('test-placeholder',Client())


def test_media_access_precedes_any_spend_reservation(monkeypatch):
 for key in ['OUTLOUD_MEDIA_SEARCH_ALLOWED','OUTLOUD_MEDIA_START_ALLOWED','OUTLOUD_TIKTOK_EVALUATION_APPROVED']:
  monkeypatch.setenv(key,'1')
 monkeypatch.setenv('APIFY_TOKEN','test-placeholder')
 def reject():raise native_access.NativeAccessUnavailable('Rejected fixture credential')
 monkeypatch.setattr(native_access,'require',reject)
 monkeypatch.setattr(research_providers,'authorize',lambda *a:pytest.fail('Invalid credentials must not reserve paid work'))
 with pytest.raises(native_access.NativeAccessUnavailable):research_providers.start_tiktok_discovery(['smart TV remote'])
 with pytest.raises(native_access.NativeAccessUnavailable):research_providers.start_instagram_discovery(['smart TV remote'],keyword=True)


def test_product_planning_does_not_spend_when_native_access_is_rejected(monkeypatch):
 import live_discovery
 from test_native_workspace_contract import product
 monkeypatch.setenv('OUTLOUD_MEDIA_SEARCH_ALLOWED','1')
 monkeypatch.setattr(research_providers,'configuration',lambda:{'enabled':True,'evaluation':True,'media':True})
 monkeypatch.setattr(research_providers,'search_brief',lambda *a:pytest.fail('Do not buy planning for unavailable collection'))
 def reject():raise native_access.NativeAccessUnavailable('Rejected fixture credential')
 monkeypatch.setattr(native_access,'require',reject)
 with pytest.raises(live_discovery.ResearchUnavailable,match='Rejected fixture'):
  live_discovery.research_live(product())


def test_scoped_token_preflight_does_not_require_private_account_read_access():
 class Client:
  def get(self,url,**kwargs):
   assert url=='https://api.apify.com/v2/acts/clockworks~tiktok-scraper'
   return httpx.Response(200)
 assert native_access.check('test-placeholder',Client())


def test_monthly_allowance_stops_other_actors_without_a_second_provider_call(monkeypatch,tmp_path):
 monkeypatch.setenv('APIFY_TOKEN','test-placeholder')
 monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'providers.sqlite3'))
 monkeypatch.setattr(native_access,'check',lambda *args:pytest.fail('Account-wide limit is already known'))
 response=httpx.Response(403,json={'error':{'type':'platform-feature-disabled','message':'Monthly usage is exhausted.'}})
 with pytest.raises(native_access.NativeCapacityUnavailable):
  native_access.raise_for_actor_start(response)
 with pytest.raises(native_access.NativeCapacityUnavailable,match='monthly account allowance'):
  require_native_access()
