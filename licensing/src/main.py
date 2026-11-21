"""Outloud licensing: FastAPI, D1, Stripe-hosted Checkout. No email dependency."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from calendar import monthrange
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

OFFER = "outloud-founding-2026"
COOKIE = "__Host-outloud-claim"
api = FastAPI(title="Outloud licensing", docs_url=None, redoc_url=None, openapi_url=None)

def config(env, name, default=""):
    return getattr(env, name, default) or default

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def key_for(session_id, secret):
    # Versioned, cryptographically pseudorandom key. Retries reproduce the same
    # key; only its hash is persisted. Keep the v1 issuer secret for recovery.
    raw = hmac.new(secret.encode(), session_id.encode(), hashlib.sha256).digest()[:15]
    chars = base64.b32encode(raw).decode()
    return "OL-" + "-".join(chars[i:i+6] for i in range(0, 24, 6))

def founding_number(slot, env):
    if slot is None: return None
    return slot + (49 if config(env, "PAYMENT_MODE", "test") == "live" else 0)

def canonical_key(value):
    return value.strip().upper()

def iso(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).isoformat()

def year_after(value):
    dt = datetime.fromisoformat(value)
    year = dt.year + 1
    return dt.replace(year=year, day=min(dt.day, monthrange(year, dt.month)[1])).isoformat()

class DB:
    def __init__(self, binding): self.binding = binding
    async def first(self, sql, *args):
        row = await self.binding.prepare(sql).bind(*args).first()
        return row.to_py() if hasattr(row, "to_py") else row
    async def run(self, sql, *args):
        return await self.binding.prepare(sql).bind(*args).run()

def env_for(request):
    env = request.scope.get("env") or request.app.state.env
    if not config(env, "LICENSE_ISSUER_V1") or not config(env, "STRIPE_SECRET_KEY"):
        raise HTTPException(503, "Checkout is being configured. Please try again shortly.")
    return env

def gateway(request, env):
    expected = config(env, "GATEWAY_SECRET")
    if not expected or not secrets.compare_digest(request.headers.get("x-outloud-gateway", ""), expected):
        raise HTTPException(403, "Use the Outloud website to complete your purchase.")

async def ensure_inventory_environment(db,env):
    if config(env,"PAYMENT_MODE","test") == "live":
        test_order=await db.first("SELECT 1 AS found FROM licenses WHERE livemode=0 UNION ALL SELECT 1 AS found FROM checkout_claims WHERE substr(session_id,1,8)='cs_test_' LIMIT 1")
        if test_order:
            raise HTTPException(503,"Live inventory must be set up separately from test orders.")

async def rate_limit(db, request, action, limit):
    ip = request.headers.get("cf-connecting-ip", request.client.host if request.client else "unknown")
    bucket = f"{action}:{digest(ip)}:{int(time.time())//600}"
    row = await db.first("INSERT INTO rate_limits(bucket,attempts) VALUES (?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1 RETURNING attempts", bucket)
    if row["attempts"] > limit: raise HTTPException(429, "Please wait a few minutes and try again.")

async def stripe(env, method, path, data=None, idem=None):
    secret = config(env, "STRIPE_SECRET_KEY")
    mode = config(env, "PAYMENT_MODE", "test")
    if mode == "test" and not secret.startswith(("sk_test_", "rk_test_")):
        raise HTTPException(503, "Sandbox is not configured.")
    if mode == "live" and not secret.startswith(("sk_live_", "rk_live_")):
        raise HTTPException(503, "Live checkout is not configured.")
    headers={"Authorization": "Bearer " + secret, "Stripe-Version":"2026-09-30.endive"}
    if idem: headers["Idempotency-Key"] = idem
    async with httpx.AsyncClient(timeout=20) as client:
        result=await client.request(method, "https://api.stripe.com/v1/" + path, data=data, headers=headers)
    if not result.is_success:
        # Never relay upstream bodies, request data or credentials to the browser.
        raise HTTPException(502, "Stripe could not complete this step. Please try again.")
    return result.json()

async def fulfill(db, env, session):
    expected_live = config(env, "PAYMENT_MODE", "test") == "live"
    if session.get("livemode") is not expected_live: raise HTTPException(400, "Wrong payment environment.")
    if session.get("payment_status") != "paid": return None
    if (session.get("mode") != "payment" or session.get("amount_subtotal") != 9999
        or session.get("currency") not in ("usd", "gbp", "eur") or session.get("metadata", {}).get("outloud_offer") != OFFER):
        raise HTTPException(422, "This payment does not match the Outloud offer.")
    sid=session["id"]
    claim=await db.first("SELECT session_id FROM checkout_claims WHERE session_id=?", sid)
    if not claim: raise HTTPException(422, "Checkout was not created by this service.")
    email=(session.get("customer_details") or {}).get("email") or session.get("customer_email")
    if not isinstance(email,str) or "@" not in email: raise HTTPException(422, "Missing receipt email.")
    payment=session.get("payment_intent")
    if isinstance(payment,dict): payment=payment.get("id")
    existing=await db.first("SELECT session_id FROM licenses WHERE session_id=?",sid)
    if not existing:
        slot=await db.first("SELECT slot FROM founding_slots WHERE session_id=?",sid)
        if not slot:
            # Grandfather an old checkout only if a real place remains.
            slot=await db.first("UPDATE founding_slots SET session_id=? WHERE slot=(SELECT slot FROM founding_slots WHERE session_id IS NULL AND claim_hash IS NULL AND issued_at IS NULL ORDER BY slot LIMIT 1) RETURNING slot",sid)
        if not slot:
            # A paid legacy checkout must not be charged without receiving a key.
            if payment:
                await stripe(env,"POST","refunds",{"payment_intent":payment},"founding-cap-refund-"+sid)
            raise HTTPException(409,"The founding batch is full. This payment has been refunded.")
    key=key_for(sid,config(env,"LICENSE_ISSUER_V1"))
    await db.run("INSERT OR IGNORE INTO licenses(session_id,key_hash,email,payment_intent,status,created_at,livemode) VALUES (?,?,?,?,CASE WHEN EXISTS(SELECT 1 FROM payment_risks WHERE payment_intent=?) THEN 'revoked' ELSE 'reserved' END,?,?)", sid,digest(key),email,payment,payment or "",iso(),int(expected_live))
    return await db.first("SELECT * FROM licenses WHERE session_id=?",sid)

@api.middleware("http")
async def security_headers(request, call_next):
    response=await call_next(request)
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    return response

@api.get("/health")
async def health(): return {"service":"outloud-licensing","ok":True}

async def release_checkout(db, env, session_id, expire_open=False):
    """Free only a Stripe-confirmed expired checkout, never an uncertain payment."""
    slot=await db.first("SELECT session_id FROM founding_slots WHERE session_id=? AND issued_at IS NULL",session_id)
    if not slot: return True
    session=await stripe(env,"GET","checkout/sessions/"+session_id)
    if session.get("livemode") is not (config(env,"PAYMENT_MODE","test")=="live") or session.get("metadata",{}).get("outloud_offer")!=OFFER:
        raise HTTPException(409,"Checkout could not be verified.")
    if session.get("payment_status")=="paid":
        await fulfill(db,env,session)
        return True
    if session.get("status")=="open" and expire_open:
        try:
            session=await stripe(env,"POST","checkout/sessions/"+session_id+"/expire")
        except HTTPException:
            # Payment may have completed while the cancellation was in flight.
            session=await stripe(env,"GET","checkout/sessions/"+session_id)
            if session.get("payment_status")=="paid":
                await fulfill(db,env,session)
                return True
    if session.get("status")!="expired": return False
    await db.run("UPDATE founding_slots SET claim_hash=NULL,session_id=NULL,hold_expires_at=NULL WHERE session_id=? AND issued_at IS NULL",session_id)
    return True

async def reconcile_due_hold(db, env):
    # Fallback when an expiry webhook is delayed. A deadline alone never frees
    # a session that might have been paid; Stripe must confirm its final state.
    orphan=await db.first("SELECT slot FROM founding_slots WHERE session_id IS NULL AND claim_hash IS NOT NULL AND hold_expires_at<? AND issued_at IS NULL ORDER BY slot LIMIT 1",int(time.time()))
    if orphan:
        await db.run("UPDATE founding_slots SET claim_hash=NULL,hold_expires_at=NULL WHERE slot=? AND session_id IS NULL AND issued_at IS NULL",orphan["slot"])
    due=await db.first("SELECT session_id FROM founding_slots WHERE session_id IS NOT NULL AND issued_at IS NULL AND hold_expires_at<? ORDER BY hold_expires_at LIMIT 1",int(time.time()))
    if due:
        try: await release_checkout(db,env,due["session_id"],expire_open=True)
        except HTTPException: pass  # Retain inventory while Stripe is unavailable.

@api.post("/api/purchase/cancel")
async def cancel_checkout(request:Request):
    env=env_for(request);gateway(request,env);db=DB(env.DB)
    if request.headers.get("origin")!=config(env,"SITE_URL").rstrip("/"):
        raise HTTPException(403,"Return to the Outloud website to cancel checkout.")
    await rate_limit(db,request,"cancel",12)
    claim=request.cookies.get(COOKIE,"")
    row=await db.first("SELECT session_id FROM checkout_claims WHERE claim_hash=? AND expires_at>?",digest(claim),int(time.time())) if claim else None
    if not row: return {"released":True}
    released=await release_checkout(db,env,row["session_id"],expire_open=True)
    paid=await db.first("SELECT session_id FROM licenses WHERE session_id=? AND status!='revoked'",row["session_id"])
    payload={"released":released}
    if paid: payload["purchase_url"]="/purchase/?session_id="+row["session_id"]
    return JSONResponse(payload,status_code=200 if released else 202)

@api.get("/api/purchase/availability")
async def availability(request:Request):
    env=env_for(request);gateway(request,env)
    await ensure_inventory_environment(DB(env.DB),env)
    await reconcile_due_hold(DB(env.DB),env)
    row=await DB(env.DB).first("SELECT COUNT(*) AS total,SUM(CASE WHEN issued_at IS NOT NULL THEN 1 ELSE 0 END) AS issued,SUM(CASE WHEN issued_at IS NULL AND (claim_hash IS NOT NULL OR session_id IS NOT NULL) THEN 1 ELSE 0 END) AS held,SUM(CASE WHEN issued_at IS NULL AND claim_hash IS NULL AND session_id IS NULL THEN 1 ELSE 0 END) AS remaining FROM founding_slots")
    direct=(await DB(env.DB).first("SELECT COALESCE(SUM(quantity),0) AS paid FROM direct_sales"))["paid"]
    mode=config(env,"PAYMENT_MODE","test")
    return {"total":row["total"],"batch_total":200,"direct_paid":direct,"total_paid":direct+(row["issued"] if mode=="live" else 0),"issued":row["issued"],"held":row["held"],"remaining":row["remaining"],"environment":mode}

@api.post("/api/purchase/start")
async def start(request:Request):
    env=env_for(request);gateway(request,env);db=DB(env.DB)
    await ensure_inventory_environment(db,env)
    await rate_limit(db,request,"checkout",6)
    await reconcile_due_hold(db,env)
    site=config(env,"SITE_URL","https://tryoutloud.pages.dev").rstrip("/")
    if request.headers.get("origin") != site: raise HTTPException(403,"Open checkout from the Outloud website.")
    # All new purchases are charged in GBP, independent of region or client input.
    currency = "gbp"
    symbol = "£"
    # Reuse an unpaid checkout when a buyer returns with browser Back. This
    # prevents repeat clicks from consuming more founding places/customers.
    previous=request.cookies.get(COOKIE, "")
    if previous:
        existing=await db.first("SELECT c.session_id FROM checkout_claims c JOIN founding_slots f ON f.session_id=c.session_id WHERE c.claim_hash=? AND c.expires_at>? AND f.issued_at IS NULL AND f.hold_expires_at>?",digest(previous),int(time.time()),int(time.time()))
        if existing:
            open_session=await stripe(env,"GET","checkout/sessions/"+existing["session_id"])
            if (open_session.get("status")=="open" and open_session.get("payment_status")=="unpaid"
                and open_session.get("currency")==currency and open_session.get("livemode") is (config(env,"PAYMENT_MODE","test")=="live")):
                return JSONResponse({"url":open_session["url"],"environment":config(env,"PAYMENT_MODE","test")})
    claim=secrets.token_urlsafe(32)
    claim_hash=digest(claim)
    expiry=int(time.time())+1860
    # One atomic D1 statement reserves a real place before Stripe is called.
    slot=await db.first("UPDATE founding_slots SET claim_hash=?,hold_expires_at=? WHERE slot=(SELECT slot FROM founding_slots WHERE session_id IS NULL AND claim_hash IS NULL AND issued_at IS NULL ORDER BY slot LIMIT 1) RETURNING slot",claim_hash,expiry)
    if not slot: raise HTTPException(409,"All founding licenses are taken or in checkout. Please check back at launch.")
    try:
        session=await stripe(env,"POST","checkout/sessions",{
            "mode":"payment","customer_creation":"always","expires_at":str(expiry),
            "line_items[0][price_data][currency]":currency,
            "adaptive_pricing[enabled]":"false",
            "line_items[0][price_data][unit_amount]":"9999",
            "line_items[0][price_data][product_data][name]":"Outloud · annual access",
            "line_items[0][price_data][product_data][images][0]":"https://files.stripe.com/links/MDB8YWNjdF8xVVZzNTlCYktuNTRXcUlpfGZsX2xpdmVfRHdFaUNwdmd0WW9TYmxUaUYxREQxcGM400ZCarZnSJ",
            "line_items[0][price_data][product_data][description]":f"12 months from receiving usable app access. Optional renewal {symbol}199.99 {currency.upper()}/year. No automatic renewal.",
            "line_items[0][quantity]":"1","metadata[outloud_offer]":OFFER,
            "payment_intent_data[metadata][outloud_offer]":OFFER,
            "integration_identifier":"outloud_"+"".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(8)),
            "success_url":site+"/purchase/?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url":site+"/?checkout=cancelled#pricing",
            "metadata[terms_version]":"2026-11-01",
            "metadata[purchase_currency]":currency,
            "custom_text[submit][message]":"Target launch: 20 December 2026.",
        },"checkout-"+digest(claim))
        await db.run("UPDATE founding_slots SET session_id=? WHERE claim_hash=?",session["id"],claim_hash)
    except Exception:
        # No checkout URL has been returned to the buyer at this point.
        await db.run("UPDATE founding_slots SET claim_hash=NULL,hold_expires_at=NULL WHERE claim_hash=? AND session_id IS NULL AND issued_at IS NULL",claim_hash)
        raise
    await db.run("INSERT INTO checkout_claims(claim_hash,session_id,expires_at) VALUES (?,?,?)",digest(claim),session["id"],int(time.time())+86400)
    response=JSONResponse({"url":session["url"],"environment":config(env,"PAYMENT_MODE","test")})
    response.set_cookie(COOKIE,claim,max_age=86400,secure=True,httponly=True,samesite="lax",path="/")
    return response

@api.get("/api/purchase/license")
async def purchase_license(request:Request,session_id:str):
    env=env_for(request);gateway(request,env);db=DB(env.DB)
    await rate_limit(db,request,"claim",60)
    claim=request.cookies.get(COOKIE,"")
    row=await db.first("SELECT session_id,expires_at FROM checkout_claims WHERE claim_hash=?",digest(claim)) if claim else None
    if not row or row["session_id"]!=session_id or row["expires_at"]<time.time():
        raise HTTPException(403,"Open this page in the browser you used to pay. If you need help, email wirebuilds@icloud.com with your receipt.")
    session=await stripe(env,"GET","checkout/sessions/"+session_id)
    # Webhooks fulfill independently. This verified return-path call also handles
    # the case where a buyer returns before Stripe delivers its webhook.
    license=await fulfill(db,env,session)
    if not license: return JSONResponse({"status":"processing"},status_code=202)
    if license["status"]=="revoked": raise HTTPException(403,"This license is no longer active. Contact support with your receipt.")
    return {"status":license["status"],"license_key":key_for(session_id,config(env,"LICENSE_ISSUER_V1")),"order":session_id,
            "environment":"live" if license["livemode"] else "test",
            "holder_name":str((session.get("customer_details") or {}).get("name") or "")[:100],"issued_at":license["created_at"],
            "founding_number":founding_number((await db.first("SELECT slot FROM founding_slots WHERE session_id=?",session_id) or {}).get("slot"),env),
            "access_starts_at":license["access_starts_at"],"access_ends_at":license["access_ends_at"],"target_launch":"2026-12-20"}

@api.post("/webhooks/stripe")
async def webhook(request:Request):
    env=env_for(request);body=await request.body()
    if len(body)>262144: raise HTTPException(413,"Payload too large.")
    values=request.headers.get("stripe-signature","").split(",")
    timestamp=next((v[2:] for v in values if v.startswith("t=")),"")
    if not timestamp.isdigit() or abs(time.time()-int(timestamp))>300: raise HTTPException(400,"Invalid signature.")
    secret=config(env,"STRIPE_WEBHOOK_SECRET")
    if not secret: raise HTTPException(503,"Webhook is not configured.")
    expected=hmac.new(secret.encode(),timestamp.encode()+b"."+body,hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected,v[3:]) for v in values if v.startswith("v1=")): raise HTTPException(400,"Invalid signature.")
    try: event=json.loads(body);item=event["data"]["object"]
    except (ValueError,KeyError,TypeError): raise HTTPException(400,"Invalid event.")
    expected_live=config(env,"PAYMENT_MODE","test")=="live"
    if event.get("livemode") is not expected_live or not str(event.get("id","")).startswith("evt_"): raise HTTPException(400,"Invalid environment.")
    db=DB(env.DB)
    if await db.first("SELECT id FROM events WHERE id=?",event["id"]): return {"received":True}
    kind=event.get("type")
    if kind in ("checkout.session.completed","checkout.session.async_payment_succeeded"):
        # Ignore unrelated checkouts, even in the same Stripe account.
        if item.get("metadata",{}).get("outloud_offer")==OFFER: await fulfill(db,env,item)
    elif kind in ("payment_intent.payment_failed","payment_intent.canceled"):
        pi_id=item.get("id","")
        if item.get("metadata",{}).get("outloud_offer")==OFFER and pi_id.startswith("pi_"):
            current=await stripe(env,"GET","payment_intents/"+pi_id)
            # A delayed failure event must not cancel a newer successful retry
            # or a payment currently awaiting authentication/settlement.
            if current.get("status") in ("requires_payment_method","canceled"):
                sessions=await stripe(env,"GET","checkout/sessions?payment_intent="+pi_id+"&limit=100")
                for session in sessions.get("data",[]):
                    if session.get("metadata",{}).get("outloud_offer")==OFFER:
                        if not await release_checkout(db,env,session["id"],expire_open=True):
                            raise HTTPException(503,"Payment status is still being confirmed.")
    elif kind in ("charge.refunded","charge.dispute.created"):
        pi=item.get("payment_intent")
        if isinstance(pi,str):
            await db.run("INSERT OR IGNORE INTO payment_risks(payment_intent,event_id) VALUES (?,?)",pi,event["id"])
            await db.run("UPDATE licenses SET status='revoked' WHERE payment_intent=?",pi)
    elif kind in ("checkout.session.async_payment_failed","checkout.session.expired"):
        await db.run("UPDATE licenses SET status='revoked' WHERE session_id=?",item.get("id",""))
        await db.run("UPDATE founding_slots SET claim_hash=NULL,session_id=NULL,hold_expires_at=NULL WHERE session_id=? AND issued_at IS NULL",item.get("id",""))
    else: return {"received":True}
    await db.run("INSERT OR IGNORE INTO events(id,type) VALUES (?,?)",event["id"],kind)
    return {"received":True}

class Activation(BaseModel):
    license_key:str=Field(min_length=10,max_length=128)
    device_id:str=Field(min_length=16,max_length=128,pattern=r"^[a-zA-Z0-9-]+$")

@api.post("/v1/licenses/activate")
async def activate(data:Activation,request:Request):
    env=env_for(request);db=DB(env.DB);await rate_limit(db,request,"activate",20)
    key=canonical_key(data.license_key)
    row=await db.first("SELECT * FROM licenses WHERE key_hash=?",digest(key))
    if not row or row["status"]=="revoked": raise HTTPException(403,"This license could not be activated.")
    if row["status"]!="reserved" and (not row["access_ends_at"] or datetime.fromisoformat(row["access_ends_at"]).timestamp()<=time.time()):
        return {"status":"expired","unlocked":False,"environment":config(env,"PAYMENT_MODE","test"),"message":"Your access year has ended. Renewal is optional."}
    device=digest(data.device_id)
    # One atomic statement enforces the two-device limit under concurrent requests.
    token=secrets.token_urlsafe(32)
    await db.run("INSERT INTO activations(session_id,device_hash,token_hash) SELECT ?,?,? WHERE (SELECT COUNT(*) FROM activations WHERE session_id=?)<2 OR EXISTS(SELECT 1 FROM activations WHERE session_id=? AND device_hash=?) ON CONFLICT(session_id,device_hash) DO UPDATE SET token_hash=excluded.token_hash",row["session_id"],device,digest(token),row["session_id"],row["session_id"],device)
    saved=await db.first("SELECT token_hash FROM activations WHERE session_id=? AND device_hash=?",row["session_id"],device)
    if not saved or saved["token_hash"]!=digest(token): raise HTTPException(409,"This license is already active on two Macs. Contact support to move it.")
    return {"status":row["status"],"unlocked":row["status"]=="active","preorder_verified":True,"environment":config(env,"PAYMENT_MODE","test"),"device_token":token,"launch_at":"2026-12-20T00:00:00+03:00","access_starts_at":row["access_starts_at"],"access_ends_at":row["access_ends_at"],"founding_number":founding_number((await db.first("SELECT slot FROM founding_slots WHERE session_id=?",row["session_id"]) or {}).get("slot"),env)}

class Lease(BaseModel):
    device_token:str=Field(min_length=32,max_length=128)

@api.post("/v1/licenses/check")
async def check(data:Lease,request:Request):
    env=env_for(request);db=DB(env.DB);await rate_limit(db,request,"check",120)
    row=await db.first("SELECT l.session_id,l.status,l.access_starts_at,l.access_ends_at,f.slot AS founding_number FROM licenses l JOIN activations a ON l.session_id=a.session_id LEFT JOIN founding_slots f ON f.session_id=l.session_id WHERE a.token_hash=?",digest(data.device_token))
    if not row: raise HTTPException(403,"License session not found.")
    active=row["status"]=="active" and bool(row["access_ends_at"]) and datetime.fromisoformat(row["access_ends_at"]).timestamp()>time.time()
    return {"license_subject":digest(row["session_id"]),"status":row["status"] if active or row["status"]!="active" else "expired","unlocked":active,"preorder_verified":row["status"] in ("reserved","active") and (row["status"]=="reserved" or active),"environment":config(env,"PAYMENT_MODE","test"),"launch_at":"2026-12-20T00:00:00+03:00","access_ends_at":row["access_ends_at"],"founding_number":founding_number(row["founding_number"],env)}

class Release(BaseModel):
    session_id:str=Field(pattern=r"^cs_[a-zA-Z0-9_]+$",max_length=300)

@api.post("/admin/release")
async def release(data:Release,request:Request):
    env=env_for(request)
    secret=config(env,"ADMIN_SECRET")
    if not secret or not secrets.compare_digest(request.headers.get("authorization",""),"Bearer "+secret): raise HTTPException(403,"Not authorized.")
    start=iso();end=year_after(start);db=DB(env.DB)
    await db.run("UPDATE licenses SET status='active',access_starts_at=?,access_ends_at=? WHERE session_id=? AND status='reserved'",start,end,data.session_id)
    row=await db.first("SELECT status,access_starts_at,access_ends_at FROM licenses WHERE session_id=?",data.session_id)
    if not row: raise HTTPException(404,"Order not found.")
    return row

class Recovery(BaseModel):
    session_id:str=Field(pattern=r"^cs_[a-zA-Z0-9_]+$",max_length=300)
    email:str=Field(min_length=3,max_length=254)

@api.post("/admin/recover")
async def recover(data:Recovery,request:Request):
    env=env_for(request);secret=config(env,"ADMIN_SECRET")
    if not secret or not secrets.compare_digest(request.headers.get("authorization",""),"Bearer "+secret): raise HTTPException(403,"Not authorized.")
    row=await DB(env.DB).first("SELECT email,status FROM licenses WHERE session_id=?",data.session_id)
    if not row or row["email"].casefold()!=data.email.strip().casefold(): raise HTTPException(404,"Matching order not found.")
    if row["status"]=="revoked": raise HTTPException(403,"License revoked.")
    return {"license_key":key_for(data.session_id,config(env,"LICENSE_ISSUER_V1")),"status":row["status"]}

# workers import is isolated so the same app can run in normal CPython tests.
try:
    from workers import asgi
    Default=asgi.entrypoint(api)
except ImportError:
    pass
