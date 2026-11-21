import asyncio
import hashlib
import hmac
import importlib.util
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

spec=importlib.util.spec_from_file_location('licensing_main',Path(__file__).parents[1]/'src/main.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Statement:
 def __init__(self,db,sql): self.db,self.sql,self.args=db,sql,()
 def bind(self,*args): self.args=args;return self
 async def first(self):
  r=self.db.execute(self.sql,self.args).fetchone();self.db.commit();return dict(r) if r else None
 async def run(self): self.db.execute(self.sql,self.args);self.db.commit()
class Binding:
 def __init__(self):
  self.db=sqlite3.connect(':memory:',check_same_thread=False);self.db.row_factory=sqlite3.Row;self.db.executescript((Path(__file__).parents[1]/'schema.sql').read_text());self.db.executescript((Path(__file__).parents[1]/'inventory.sql').read_text());self.db.executescript((Path(__file__).parents[1]/'migrations/2026-11-01-wise-direct-sales.sql').read_text())
 def prepare(self,sql): return Statement(self.db,sql)

@pytest.fixture
def setup(monkeypatch):
 env=SimpleNamespace(DB=Binding(),LICENSE_ISSUER_V1='issuer-test-only-'+'x'*32,STRIPE_SECRET_KEY='sk_test_fixture',GATEWAY_SECRET='gateway-test-only',STRIPE_WEBHOOK_SECRET='whsec_fixture',ADMIN_SECRET='admin-test-only',PAYMENT_MODE='test',SITE_URL='https://tryoutloud.pages.dev')
 paid={'id':'cs_test_fixture','livemode':False,'mode':'payment','amount_subtotal':9999,'currency':'usd','payment_status':'unpaid','metadata':{'outloud_offer':m.OFFER},'customer_details':{'email':'buyer@example.com'},'payment_intent':'pi_fixture','url':'https://checkout.stripe.com/c/pay/cs_test_fixture'}
 async def stripe(*args,**kwargs): return paid.copy()
 monkeypatch.setattr(m,'stripe',stripe);m.api.state.env=env
 with TestClient(m.api) as client: yield client,env,paid

def purchase(c):
 h={'x-outloud-gateway':'gateway-test-only','origin':'https://tryoutloud.pages.dev'}
 r=c.post('/api/purchase/start',headers=h);assert r.status_code==200,r.text
 cookie=r.cookies.get(m.COOKIE);assert cookie
 c.cookies.set(m.COOKIE,cookie)
 return {'x-outloud-gateway':'gateway-test-only'}

def claim(c,h): return c.get('/api/purchase/license?session_id=cs_test_fixture',headers=h)

def webhook(c,env,paid,kind='checkout.session.completed',eid='evt_fixture'):
 event={'id':eid,'type':kind,'livemode':False,'data':{'object':paid}}
 body=json.dumps(event).encode();t=str(int(time.time()));sig=hmac.new(env.STRIPE_WEBHOOK_SECRET.encode(),t.encode()+b'.'+body,hashlib.sha256).hexdigest()
 return c.post('/webhooks/stripe',content=body,headers={'stripe-signature':f't={t},v1={sig}'})

def test_unpaid_redirect_does_not_issue_and_claim_is_browser_bound(setup):
 c,e,s=setup;h=purchase(c)
 assert claim(c,h).status_code==202
 assert e.DB.db.execute('select count(*) from licenses').fetchone()[0]==0
 c.cookies.clear();assert claim(c,h).status_code==403
 assert c.post('/api/purchase/start',headers={'x-outloud-gateway':'gateway-test-only','origin':'https://evil.example'}).status_code==403

def test_paid_webhook_key_download_retry_reserved_then_activate(setup):
 c,e,s=setup;h=purchase(c);s['payment_status']='paid'
 assert webhook(c,e,s).status_code==200
 first=claim(c,h).json();assert first['license_key'].startswith('OL-') and first['status']=='reserved'
 assert first['founding_number']==1
 assert webhook(c,e,s,eid='evt_retry').status_code==200
 assert claim(c,h).json()['license_key']==first['license_key']
 assert e.DB.db.execute('select count(*) from licenses').fetchone()[0]==1
 assert first['license_key'] not in str(list(e.DB.db.execute('select * from licenses').fetchone()))
 body={'license_key':first['license_key'],'device_id':'installation-123456789'}
 r=c.post('/v1/licenses/activate',json=body);assert r.json()['unlocked'] is False
 assert c.post('/admin/release',json={'session_id':s['id']}).status_code==403
 r=c.post('/admin/release',json={'session_id':s['id']},headers={'authorization':'Bearer admin-test-only'});assert r.status_code==200
 before=r.json()['access_starts_at'];end=r.json()['access_ends_at'];assert int(end[:4])==int(before[:4])+1
 assert c.post('/admin/release',json={'session_id':s['id']},headers={'authorization':'Bearer admin-test-only'}).json()['access_starts_at']==before
 token=c.post('/v1/licenses/activate',json=body).json()['device_token']
 assert c.post('/v1/licenses/check',json={'device_token':token}).json()['unlocked']
 for device in ['installation-222222222','installation-123456789']:
  assert c.post('/v1/licenses/activate',json={**body,'device_id':device}).status_code==200
 assert c.post('/v1/licenses/activate',json={**body,'device_id':'installation-333333333'}).status_code==409

def test_refund_before_fulfillment_revokes_and_invalid_signature_fails(setup):
 c,e,s=setup;h=purchase(c);s['payment_status']='paid'
 assert c.post('/webhooks/stripe',json={},headers={'stripe-signature':'bad'}).status_code==400
 assert webhook(c,e,{'payment_intent':'pi_fixture'},'charge.refunded','evt_refund').status_code==200
 assert webhook(c,e,s).status_code==200
 assert claim(c,h).status_code==403

def test_wrong_environment_price_and_unknown_checkout_fail(setup):
 c,e,s=setup;purchase(c);s['payment_status']='paid'
 for field,value in [('livemode',True),('amount_subtotal',1),('id','cs_test_someone_else')]:
  changed={**s,field:value}
  assert webhook(c,e,changed,eid='evt_'+field).status_code in (400,422)
 assert e.DB.db.execute('select count(*) from licenses').fetchone()[0]==0

def test_expired_and_revoked_license_sessions_do_not_unlock(setup):
 c,e,s=setup;h=purchase(c);s['payment_status']='paid';key=claim(c,h).json()['license_key']
 e.DB.db.execute("update licenses set status='active',access_starts_at='2020-01-01T00:00:00+00:00',access_ends_at='2021-01-01T00:00:00+00:00'");e.DB.db.commit()
 assert c.post('/v1/licenses/activate',json={'license_key':key,'device_id':'installation-123456789'}).json()['status']=='expired'
 assert m.year_after('2024-02-29T12:00:00+00:00')=='2025-02-28T12:00:00+00:00'

def test_recovery_requires_owner_authorization_and_matching_receipt(setup):
 c,e,s=setup;h=purchase(c);s['payment_status']='paid';expected=claim(c,h).json()['license_key']
 body={'session_id':s['id'],'email':'buyer@example.com'}
 assert c.post('/admin/recover',json=body).status_code==403
 auth={'authorization':'Bearer admin-test-only'}
 assert c.post('/admin/recover',json={**body,'email':'wrong@example.com'},headers=auth).status_code==404
 assert c.post('/admin/recover',json=body,headers=auth).json()['license_key']==expected

def test_preorder_session_restores_without_starting_access_year(setup):
 c,e,s=setup;h=purchase(c);s['payment_status']='paid';key=claim(c,h).json()['license_key']
 r=c.post('/v1/licenses/activate',json={'license_key':key,'device_id':'preorder-installation-1234'})
 assert r.status_code==200
 data=r.json();assert data['status']=='reserved' and data['preorder_verified'] and not data['unlocked']
 assert data['access_starts_at'] is None and data['access_ends_at'] is None
 restored=c.post('/v1/licenses/check',json={'device_token':data['device_token']}).json()
 assert restored['status']=='reserved' and restored['preorder_verified'] and not restored['unlocked']
 assert restored['access_ends_at'] is None
 assert restored['launch_at']=='2026-12-20T00:00:00+03:00'
 assert webhook(c,e,{'payment_intent':'pi_fixture'},'charge.refunded','evt_preorder_refund').status_code==200
 denied=c.post('/v1/licenses/check',json={'device_token':data['device_token']}).json()
 assert denied['status']=='revoked' and not denied['preorder_verified'] and not denied['unlocked']

def availability(c):
 return c.get('/api/purchase/availability',headers={'x-outloud-gateway':'gateway-test-only'}).json()

def test_inventory_paid_retry_refund_and_expiry(setup):
 c,e,s=setup
 assert availability(c)=={'total':151,'batch_total':200,'direct_paid':49,'total_paid':49,'issued':0,'held':0,'remaining':151,'environment':'test'}
 h=purchase(c)
 assert availability(c)['held']==1 and availability(c)['remaining']==150
 s['payment_status']='paid'
 assert claim(c,h).status_code==200
 assert webhook(c,e,s).status_code==200
 assert availability(c)['issued']==1 and availability(c)['held']==0
 assert webhook(c,e,{'payment_intent':'pi_fixture'},'charge.refunded','evt_capacity_refund').status_code==200
 assert availability(c)['remaining']==151
 s['id']='cs_test_abandoned';purchase(c)
 assert availability(c)['remaining']==150
 assert webhook(c,e,s,'checkout.session.expired','evt_expired').status_code==200
 assert availability(c)['remaining']==151

def test_final_slot_is_reserved_before_stripe_and_sold_out_blocks(setup,monkeypatch):
 c,e,s=setup
 e.DB.db.execute("UPDATE founding_slots SET session_id='occupied_'||slot,issued_at='2026-10-30' WHERE slot<151");e.DB.db.commit()
 async def upstream(env,method,path,data=None,idem=None):
  # A second concurrent request sees no slot while the first is awaiting Stripe.
  state=await m.DB(env.DB).first('SELECT COUNT(*) AS n FROM founding_slots WHERE claim_hash IS NULL AND session_id IS NULL')
  assert state['n']==0
  assert int(data['expires_at'])>time.time()+1800
  return s.copy()
 monkeypatch.setattr(m,'stripe',upstream)
 purchase(c)
 assert availability(c)['remaining']==0
 c.cookies.clear()  # A different buyer cannot claim the final held place.
 r=c.post('/api/purchase/start',headers={'x-outloud-gateway':'gateway-test-only','origin':'https://tryoutloud.pages.dev'})
 assert r.status_code==409
 assert availability(c)['held']==1

def test_stripe_failure_releases_unreturned_hold(setup,monkeypatch):
 c,e,s=setup
 async def unavailable(*args,**kwargs): raise m.HTTPException(502,'Stripe unavailable')
 monkeypatch.setattr(m,'stripe',unavailable)
 r=c.post('/api/purchase/start',headers={'x-outloud-gateway':'gateway-test-only','origin':'https://tryoutloud.pages.dev'})
 assert r.status_code==502 and availability(c)['remaining']==151


def test_founding_place_is_database_backed_and_survives_restore(setup):
 c,e,s=setup;h=purchase(c);s['payment_status']='paid';key=claim(c,h).json()['license_key']
 data=c.post('/v1/licenses/activate',json={'license_key':key,'device_id':'founding-number-installation'}).json()
 actual=e.DB.db.execute('select slot from founding_slots where session_id=?',(s['id'],)).fetchone()[0]
 assert data['founding_number']==actual and 1<=actual<=151
 assert claim(c,h).json()['founding_number']==data['founding_number']
 restored=c.post('/v1/licenses/check',json={'device_token':data['device_token']}).json()
 assert restored['founding_number']==actual
 webhook(c,e,{'payment_intent':'pi_fixture'},'charge.refunded','evt_number_refund')
 revoked=c.post('/v1/licenses/check',json={'device_token':data['device_token']}).json()
 assert revoked['founding_number'] is None and not revoked['preorder_verified']


@pytest.mark.parametrize("currency,symbol",[("usd","$"),("gbp","£"),("eur","€")])
def test_fixed_currency_checkout_and_fulfillment(setup,monkeypatch,currency,symbol):
 c,e,s=setup
 captured={}
 async def upstream(env,method,path,data=None,idem=None):
  if data: captured.update(data)
  return {**s,"currency":currency}
 monkeypatch.setattr(m,'stripe',upstream)
 r=c.post('/api/purchase/start',json={"currency":currency},headers={'x-outloud-gateway':'gateway-test-only','origin':e.SITE_URL,'x-outloud-country':{'usd':'US','gbp':'GB','eur':'FR'}[currency]})
 assert r.status_code==200
 assert captured['line_items[0][price_data][currency]']==currency
 assert captured['line_items[0][price_data][unit_amount]']=='9999'
 assert captured['adaptive_pricing[enabled]']=='false'
 assert symbol+'199.99' in captured['line_items[0][price_data][product_data][description]']
 assert 'credits' not in captured['line_items[0][price_data][product_data][description]'].lower()
 assert captured['custom_text[submit][message]']=='Target launch: 20 December 2026.'
 s.update(currency=currency,payment_status='paid')
 assert webhook(c,e,s).status_code==200
 assert e.DB.db.execute('select count(*) from licenses').fetchone()[0]==1

def test_body_cannot_override_automatic_currency(setup,monkeypatch):
 c,e,s=setup;captured={}
 async def upstream(env,method,path,data=None,idem=None):
  captured.update(data or {});return s.copy()
 monkeypatch.setattr(m,'stripe',upstream)
 r=c.post('/api/purchase/start',json={"currency":"gbp"},headers={'x-outloud-gateway':'gateway-test-only','origin':e.SITE_URL,'x-outloud-country':'KE'})
 assert r.status_code==200
 assert captured['line_items[0][price_data][currency]']=='usd'


def test_direct_wise_sales_are_separate_from_stripe_test_activity(setup):
 c,e,s=setup
 before=availability(c);assert before['direct_paid']==49 and before['total_paid']==49 and before['remaining']==151
 h=purchase(c);s['payment_status']='paid';assert claim(c,h).status_code==200
 after=availability(c);assert after['direct_paid']==49 and after['total_paid']==49
 assert after['issued']==1 and after['remaining']==150
 e.PAYMENT_MODE='live'
 assert c.get('/api/purchase/availability',headers={'x-outloud-gateway':'gateway-test-only'}).status_code==503
 e.PAYMENT_MODE='test'
 assert webhook(c,e,{'payment_intent':'pi_fixture'},'charge.refunded','evt_direct_separate_refund').status_code==200
 assert availability(c)['direct_paid']==49 and availability(c)['remaining']==151


def test_back_button_reuses_open_checkout_without_another_hold(setup,monkeypatch):
 c,e,s=setup;s['status']='open';calls=[]
 original=m.stripe
 async def recording(*args,**kwargs):
  calls.append((args[1],args[2]));return await original(*args,**kwargs)
 monkeypatch.setattr(m,'stripe',recording)
 purchase(c);before=availability(c)
 assert c.post('/api/purchase/start',headers={'x-outloud-gateway':'gateway-test-only','origin':e.SITE_URL}).status_code==200
 assert availability(c)==before
 assert calls==[('POST','checkout/sessions'),('GET','checkout/sessions/cs_test_fixture')]


def test_forged_key_and_device_token_do_not_unlock(setup):
 c,e,s=setup
 r=c.post('/v1/licenses/activate',json={'license_key':'OL-AAAAAA-BBBBBB-CCCCCC-DDDDDD','device_id':'forged-installation-1234'})
 assert r.status_code==403
 assert c.post('/v1/licenses/check',json={'device_token':'forged-token-'+'x'*32}).status_code==403
 for _ in range(19):
  assert c.post('/v1/licenses/activate',json={'license_key':'OL-AAAAAA-BBBBBB-CCCCCC-DDDDDD','device_id':'forged-installation-1234'}).status_code==403
 assert c.post('/v1/licenses/activate',json={'license_key':'OL-AAAAAA-BBBBBB-CCCCCC-DDDDDD','device_id':'forged-installation-1234'}).status_code==429


def test_new_checkout_attempts_are_throttled(setup):
 c,e,s=setup
 e.DB.db.execute("INSERT INTO rate_limits(bucket,attempts) VALUES (?,6)",(f'checkout:{m.digest("testclient")}:{int(time.time())//600}',));e.DB.db.commit()
 r=c.post('/api/purchase/start',headers={'x-outloud-gateway':'gateway-test-only','origin':e.SITE_URL})
 assert r.status_code==429 and availability(c)['remaining']==151


def test_clean_live_inventory_starts_with_only_real_purchases(setup):
 c,e,s=setup;e.PAYMENT_MODE='live'
 assert availability(c)['total_paid']==49 and availability(c)['remaining']==151
 e.DB.db.execute("UPDATE founding_slots SET session_id='cs_live_real' WHERE slot=1")
 e.DB.db.execute("INSERT INTO licenses(session_id,key_hash,email,status,created_at,livemode) VALUES ('cs_live_real','hash','buyer@example.com','reserved','2026-11-01',1)")
 e.DB.db.commit()
 data=availability(c);assert data['total_paid']==50 and data['remaining']==150
 assert data['total_paid']+data['remaining']+data['held']==200


def test_live_start_rejects_test_database_even_with_only_unpaid_sessions(setup):
 c,e,s=setup;purchase(c);e.PAYMENT_MODE='live'
 r=c.post('/api/purchase/start',headers={'x-outloud-gateway':'gateway-test-only','origin':e.SITE_URL})
 assert r.status_code==503


@pytest.mark.parametrize("country", "AT BE BG HR CY EE FI FR DE GR IE IT LV LT LU MT NL PT SK SI ES AD MC SM VA ME XK AX BL GF GP MQ MF PM RE YT TF IC EA".split())
def test_all_euro_regions_use_fixed_eur_price(setup,monkeypatch,country):
 c,e,s=setup;captured={}
 async def upstream(env,method,path,data=None,idem=None):
  captured.update(data or {});return {**s,'currency':'eur'}
 monkeypatch.setattr(m,'stripe',upstream)
 r=c.post('/api/purchase/start',headers={'x-outloud-gateway':'gateway-test-only','origin':e.SITE_URL,'x-outloud-country':country})
 assert r.status_code==200
 assert captured['line_items[0][price_data][currency]']=='eur'
 assert captured['line_items[0][price_data][unit_amount]']=='9999'


@pytest.mark.parametrize("country",['DK','SE','PL','RO','HU','CZ','CH','KE'])
def test_non_euro_local_currencies_keep_usd_offer(setup,monkeypatch,country):
 c,e,s=setup;captured={}
 async def upstream(env,method,path,data=None,idem=None):
  captured.update(data or {});return s.copy()
 monkeypatch.setattr(m,'stripe',upstream)
 r=c.post('/api/purchase/start',headers={'x-outloud-gateway':'gateway-test-only','origin':e.SITE_URL,'x-outloud-country':country})
 assert r.status_code==200 and captured['line_items[0][price_data][currency]']=='usd'

@pytest.mark.parametrize('slot,expected', [(1,50),(2,51),(151,200),(None,None)])
def test_live_founding_numbers_follow_the_49_paid_direct_members(setup,slot,expected):
 c,e,s=setup;e.PAYMENT_MODE='live'
 assert m.founding_number(slot,e)==expected

def test_live_number_stays_consistent_on_purchase_activation_and_restore(setup):
 c,e,s=setup;e.PAYMENT_MODE='live';s.update(id='cs_live_fixture',livemode=True)
 h=purchase(c);s['payment_status']='paid'
 first=c.get('/api/purchase/license?session_id=cs_live_fixture',headers=h)
 assert first.status_code==200 and first.json()['founding_number']==50
 r=c.post('/v1/licenses/activate',json={'license_key':first.json()['license_key'],'device_id':'live-installation-1234'})
 assert r.status_code==200 and r.json()['founding_number']==50
 assert c.post('/v1/licenses/check',json={'device_token':r.json()['device_token']}).json()['founding_number']==50
 assert availability(c)['total_paid']==50 and availability(c)['remaining']==150

def cancellation_headers(e):
 return {'x-outloud-gateway':e.GATEWAY_SECRET,'origin':e.SITE_URL}

def mock_checkout_state(monkeypatch,s,pi_status='requires_payment_method',race=False):
 calls=[]
 async def upstream(env,method,path,data=None,idem=None):
  calls.append((method,path))
  if path.startswith('payment_intents/'):
   return {'id':'pi_fixture','status':pi_status}
  if path.startswith('checkout/sessions?'):
   return {'data':[s.copy()]}
  if path.endswith('/expire'):
   if race:
    s.update(payment_status='paid',status='complete')
    raise m.HTTPException(502,'Stripe session completed during cancellation')
   s['status']='expired'
  return s.copy()
 monkeypatch.setattr(m,'stripe',upstream)
 return calls

def test_return_to_site_expires_only_own_unpaid_checkout(setup,monkeypatch):
 c,e,s=setup;purchase(c);s['status']='open';calls=mock_checkout_state(monkeypatch,s)
 r=c.post('/api/purchase/cancel',headers=cancellation_headers(e))
 assert r.status_code==200 and r.json()['released']
 assert availability(c)['remaining']==151 and availability(c)['held']==0
 assert ('POST','checkout/sessions/'+s['id']+'/expire') in calls
 assert c.post('/api/purchase/cancel',headers=cancellation_headers(e)).status_code==200
 assert len([x for x in calls if x[0]=='POST'])==1
 assert e.DB.db.execute('select count(*) from licenses').fetchone()[0]==0

def test_cancel_cannot_target_another_browser_or_cross_site(setup,monkeypatch):
 c,e,s=setup;purchase(c);s['status']='open';calls=mock_checkout_state(monkeypatch,s)
 assert c.post('/api/purchase/cancel',headers={**cancellation_headers(e),'origin':'https://other.example'}).status_code==403
 c.cookies.clear()
 assert c.post('/api/purchase/cancel',json={'session_id':s['id']},headers=cancellation_headers(e)).json()['released']
 assert availability(c)['held']==1 and calls==[]

@pytest.mark.parametrize('race',[False,True])
def test_cancel_never_releases_payment_completed_before_or_during_return(setup,monkeypatch,race):
 c,e,s=setup;purchase(c);s['status']='open'
 if not race:s.update(payment_status='paid',status='complete')
 mock_checkout_state(monkeypatch,s,race=race)
 r=c.post('/api/purchase/cancel',headers=cancellation_headers(e))
 assert r.status_code==200 and r.json()['released']
 assert availability(c)['issued']==1 and availability(c)['remaining']==150
 assert c.get('/api/purchase/license?session_id='+s['id'],headers={'x-outloud-gateway':e.GATEWAY_SECRET}).status_code==200

def test_pending_bank_payment_keeps_reservation_until_definitive_result(setup,monkeypatch):
 c,e,s=setup;purchase(c);s.update(status='complete',payment_status='unpaid')
 mock_checkout_state(monkeypatch,s)
 r=c.post('/api/purchase/cancel',headers=cancellation_headers(e))
 assert r.status_code==202 and r.json()['released'] is False
 assert availability(c)['held']==1

def test_card_decline_webhook_closes_session_and_restores_place_once(setup,monkeypatch):
 c,e,s=setup;purchase(c);s['status']='open';calls=mock_checkout_state(monkeypatch,s)
 pi={'id':'pi_fixture','metadata':{'outloud_offer':m.OFFER},'status':'requires_payment_method'}
 assert webhook(c,e,pi,'payment_intent.payment_failed','evt_declined').status_code==200
 assert availability(c)['held']==0 and availability(c)['remaining']==151
 assert webhook(c,e,pi,'payment_intent.payment_failed','evt_declined').status_code==200
 assert len([x for x in calls if x[0]=='POST'])==1

@pytest.mark.parametrize('status',['processing','requires_action','succeeded'])
def test_delayed_failure_event_does_not_interrupt_a_new_payment_attempt(setup,monkeypatch,status):
 c,e,s=setup;purchase(c);s['status']='open';calls=mock_checkout_state(monkeypatch,s,pi_status=status)
 pi={'id':'pi_fixture','metadata':{'outloud_offer':m.OFFER},'status':'requires_payment_method'}
 assert webhook(c,e,pi,'payment_intent.payment_failed','evt_old_failure').status_code==200
 assert availability(c)['held']==1
 assert not any(method=='POST' for method,path in calls)

@pytest.mark.parametrize('paid',[False,True])
def test_due_checkout_reconciles_with_stripe_when_expiry_webhook_is_delayed(setup,monkeypatch,paid):
 c,e,s=setup;purchase(c)
 e.DB.db.execute('update founding_slots set hold_expires_at=?',(int(time.time())-10,));e.DB.db.commit()
 s.update(status='complete' if paid else 'expired',payment_status='paid' if paid else 'unpaid')
 mock_checkout_state(monkeypatch,s)
 data=availability(c)
 assert data['held']==0 and data['issued']==int(paid) and data['remaining']==(150 if paid else 151)

def test_due_checkout_is_not_freed_when_stripe_cannot_confirm_status(setup,monkeypatch):
 c,e,s=setup;purchase(c)
 e.DB.db.execute('update founding_slots set hold_expires_at=?',(int(time.time())-10,));e.DB.db.commit()
 async def unavailable(*args,**kwargs):raise m.HTTPException(502,'Stripe temporarily unavailable')
 monkeypatch.setattr(m,'stripe',unavailable)
 assert availability(c)['held']==1
 assert c.post('/api/purchase/cancel',headers=cancellation_headers(e)).status_code==502
 assert e.DB.db.execute('select count(*) from founding_slots where session_id is not null').fetchone()[0]==1
