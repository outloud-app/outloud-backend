"""Local-only discovery trial. No billing, model calls or platform scraping."""
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
import time
import threading
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends
from desktop_access import desktop_identity
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from product_profile import rank_catalog, clean, research_project
from live_discovery import research_live, cache_key, ResearchUnavailable, VERSION as SEARCH_VERSION, author_label, provider_cache_signature

HERE = Path(__file__).parent
DB = Path(os.environ.get("TRIAL_DB", str(HERE / ".data/trial.sqlite3")))
ORIGINS = {"http://127.0.0.1:4321", "http://localhost:4321"}
CATALOG = json.loads((HERE / "catalog.json").read_text())
CATEGORIES = {row[0] for row in json.loads((HERE / "data/categories.json").read_text())}
CATEGORY_KEYWORDS = json.loads((HERE / "data/category-keywords.json").read_text())
LOCAL_TESTING = os.environ.get("OUTLOUD_LOCAL_TESTING") == "1"
LIVE_SEARCH = os.environ.get("OUTLOUD_LIVE_SEARCH") == "1"
RESEARCH_LOCK = threading.Lock()
RESEARCH_LOCKS = {}

@contextmanager
def research_lock(key):
    # Deduplicate the same research, while independent products run concurrently.
    # Reference counts remove idle locks instead of accumulating them forever.
    with RESEARCH_LOCK:
        lock, users = RESEARCH_LOCKS.get(key, (threading.Lock(), 0))
        RESEARCH_LOCKS[key] = (lock, users + 1)
    try:
        with lock:
            yield
    finally:
        with RESEARCH_LOCK:
            _, users = RESEARCH_LOCKS[key]
            if users == 1:
                del RESEARCH_LOCKS[key]
            else:
                RESEARCH_LOCKS[key] = (lock, users - 1)

SEARCH_DAILY_LIMIT = min(200,int(os.environ.get('OUTLOUD_SEARCH_DAILY_LIMIT','80'))) if LOCAL_TESTING else 80
DAILY_BUDGET = 500 if LOCAL_TESTING else 30
SESSION_DAILY_LIMIT = 50 if LOCAL_TESTING else 3
IP_DAILY_LIMIT = 300 if LOCAL_TESTING else 12


@contextmanager
def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
      CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL,
        results TEXT NOT NULL, created REAL NOT NULL,
        published INTEGER NOT NULL DEFAULT 0, consent_at REAL, public_data TEXT,
        rating INTEGER, review TEXT, reviewed REAL,
        cover TEXT NOT NULL DEFAULT '', preview_url TEXT NOT NULL DEFAULT '');
      CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner,created);
      CREATE TABLE IF NOT EXISTS limits (key TEXT PRIMARY KEY, hits INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS research_cache (key TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS metadata_cache (url TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL);
    """)
    # Local schema upgrades preserve projects made during evaluation.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
    for column in ("cover", "preview_url", "icon", "reviewer_name", "reviewer_email"):
        if column not in columns:
            connection.execute(f"ALTER TABLE projects ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    if "review_public" not in columns:
        connection.execute("ALTER TABLE projects ADD COLUMN review_public INTEGER NOT NULL DEFAULT 0")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def public_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.lower().startswith("http://"):
        value = "https://" + value[7:]
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value):
        value = "https://" + value
    if not value.lower().startswith("https://"):
        raise ValueError("Use a website, App Store or Google Play link.")
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Use a public HTTPS link without a login or custom port.")
    host = parsed.hostname.lower()
    if "." not in host or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("That link is not a public website.")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("Private network links are not supported.")
    except ValueError as error:
        if "not supported" in str(error):
            raise
    return value


def safe_asset(value: str) -> str:
    if not value:
        return ""
    try:
        public_url(value)
        host = urlsplit(value).hostname
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return value if addresses and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses) else ""
    except (ValueError, OSError):
        return ""


class FollowedSource(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    platform: str
    kind: str = "topic"
    url: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def name_valid(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 or c in "<>" for c in value):
            raise ValueError("Use a plain-text account or topic name.")
        return value

    @field_validator("platform")
    @classmethod
    def platform_valid(cls, value):
        if value not in ("X", "Reddit", "TikTok", "Instagram", "Web"):
            raise ValueError("Choose a supported source platform.")
        return value

    @field_validator("kind")
    @classmethod
    def kind_valid(cls, value):
        if value not in ("topic", "account"):
            raise ValueError("Choose an account or topic.")
        return value

    @field_validator("url")
    @classmethod
    def url_valid(cls, value):
        # This is an identity hint, never a URL to fetch without metadata safety checks.
        if value:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port:
                raise ValueError("Use a public HTTPS profile link.")
        return value


class Project(BaseModel):
    name: str = Field(min_length=2, max_length=70)
    platform: str
    status: str
    url: str = Field(default="", max_length=500)
    description: str = Field(min_length=30, max_length=1200)
    category: str
    audience: str = Field(default="", max_length=240)
    problem: str = Field(default="", max_length=400)
    features: list[str] = Field(default_factory=list, max_length=8)
    competitors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list, max_length=50)

    followed_sources: list[FollowedSource] = Field(default_factory=list, max_length=100)

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        # Preserve existing product/cache identities when no sources are followed.
        if not data.get("followed_sources"):
            data.pop("followed_sources", None)
        return data

    @field_validator("keywords")
    @classmethod
    def keywords_valid(cls, values):
        result, seen = [], set()
        for value in values:
            for word in value.replace("，", ",").split(","):
                word = word.strip()
                if "<" in word or ">" in word or any(ord(char) < 32 for char in word):
                    raise ValueError("Use plain-text research keywords separated by commas.")
                if word and word.casefold() not in seen:
                    result.append(word); seen.add(word.casefold())
        if len(",".join(values)) > 100:
            raise ValueError("Research keywords must fit within 100 characters, including commas.")
        return result

    @field_validator("competitors")
    @classmethod
    def competitors_valid(cls,values):
        if any(len(value)>300 or "<" in value or ">" in value for value in values):
            raise ValueError("Use competitor names or public links of up to 300 characters each.")
        return [value.strip() for value in values if value.strip()]

    @field_validator("features")
    @classmethod
    def features_valid(cls, values):
        if any(len(value)>180 or "<" in value or ">" in value for value in values):
            raise ValueError("Use short, plain-text features.")
        return [value.strip() for value in values if value.strip()]

    @field_validator("name", "description")
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if "<" in value or ">" in value or not value:
            raise ValueError("Please use plain text.")
        return value

    @field_validator("audience", "problem")
    @classmethod
    def context_valid(cls, value):
        if "<" in value or ">" in value:
            raise ValueError("Please use plain text.")
        return value.strip()

    @field_validator("platform")
    @classmethod
    def platform_valid(cls, value):
        if value not in ("iOS", "Android", "Web", "Mac", "Windows", "Linux", "HarmonyOS", "Other"):
            raise ValueError("Choose a platform.")
        return value

    @field_validator("status")
    @classmethod
    def status_valid(cls, value):
        if value not in ("launched", "unlaunched"):
            raise ValueError("Choose your launch status.")
        return value

    @field_validator("category")
    @classmethod
    def category_valid(cls, value):
        if value not in CATEGORIES:
            raise ValueError("Choose a category.")
        return value

    @field_validator("url")
    @classmethod
    def url_valid(cls, value):
        return public_url(value)


class Feedback(BaseModel):
    rating: int = Field(ge=1, le=5)
    review: str = Field(default="", max_length=600)
    public: bool = False  # Legacy clients promised privacy; never publish those submissions silently.
    reviewer_name: str = Field(default="", max_length=55)
    reviewer_email: str = Field(default="", max_length=254)

    @field_validator("reviewer_email")
    @classmethod
    def valid_private_email(cls, value):
        value = value.strip()
        if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address or leave it blank.")
        return value


class Publication(BaseModel):
    consent: bool
    name: str = Field(min_length=2, max_length=70)
    description: str = Field(min_length=20, max_length=180)
    url: str = Field(default="", max_length=500)
    icon: str = Field(default="", max_length=1000)

    @field_validator("url")
    @classmethod
    def url_valid(cls, value):
        return public_url(value)

    @field_validator("icon")
    @classmethod
    def icon_valid(cls, value):
        return public_url(value)


app = FastAPI(title="Outloud local discovery trial", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=list(ORIGINS), allow_credentials=True,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])


@app.middleware("http")
async def local_only(request: Request, call_next):
    # Keep this evaluation service off public interfaces and unrelated sites.
    if request.url.hostname not in ("127.0.0.1", "localhost", "testserver"):
        return Response(status_code=403)
    native_request=request.url.path.startswith("/desktop/") and not request.headers.get("origin") and request.headers.get("authorization", "").startswith("Bearer ")
    if request.method in ("POST", "DELETE") and request.headers.get("origin") not in ORIGINS and not native_request:
        return Response(status_code=403)
    if int(request.headers.get("content-length", "0") or 0) > 8192:
        return Response(status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def owner(request):
    if getattr(request.state,"desktop_owner",None):
        return request.state.desktop_owner
    token = request.cookies.get("outloud_trial", "")
    with connect() as db:
        row = db.execute("SELECT id FROM sessions WHERE id=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "Your session expired. Return to the trial welcome screen.")
    return token


def owned(request, project_id):
    identity = owner(request)
    with connect() as db:
        row = db.execute("SELECT * FROM projects WHERE id=? AND owner=?", (project_id, identity)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found in this browser.")
    return row


def consume(db, key, cap):
    db.execute("INSERT INTO limits(key,hits) VALUES(?,0) ON CONFLICT(key) DO NOTHING", (key,))
    result = db.execute("UPDATE limits SET hits=hits+1 WHERE key=? AND hits<?", (key, cap))
    if result.rowcount != 1:
        raise HTTPException(429, "Today's trial research limit has been reached. Your existing results are still available.")


def match(project, metadata=None):
    return rank_catalog(project, CATALOG, CATEGORY_KEYWORDS, metadata)



def project_from_record(data):
    """Read valid legacy profiles without weakening new-project input rules.

    Older versions allowed short descriptions and null optional lists. Retain
    the user's actual words; the prefix is an attribution, not a new capability.
    """
    data=dict(data)
    for field in ('keywords','competitors','features'):
        if data.get(field) is None:data[field]=[]
    description=data.get('description','')
    if isinstance(description,str) and 10<=len(description.strip())<30:
        data['description']='User description: '+description.strip()
    return Project(**data)


@app.get("/health")
def health():
    from research_routing import mode
    cached_only=os.environ.get('OUTLOUD_RESEARCH_CACHE_ONLY')=='1'
    return {"ok": True, "mode": "local", "generation": False,
            "live_search": LIVE_SEARCH, "search_provider": ('collected_store' if cached_only else 'apify_native' if mode()=='native' else 'exa_free_mcp') if LIVE_SEARCH else None,
            "cached_only":cached_only,"developer_testing": LOCAL_TESTING, "trials_per_day": SESSION_DAILY_LIMIT}


@app.post("/session")
def session(request: Request, response: Response):
    token = request.cookies.get("outloud_trial", "")
    with connect() as db:
        if not db.execute("SELECT id FROM sessions WHERE id=?", (token,)).fetchone():
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES(?,?)", (token, time.time()))
    response.set_cookie("outloud_trial", token, httponly=True, samesite="lax", max_age=604800)
    return {"ok": True}


@app.get("/projects")
def my_projects(request: Request):
    identity = owner(request)
    with connect() as db:
        rows = db.execute("SELECT id,data,published FROM projects WHERE owner=? ORDER BY created DESC", (identity,)).fetchall()
    return [{"id": row["id"], **json.loads(row["data"]), "published": bool(row["published"])} for row in rows]


@app.post("/research")
def research(project: Project, request: Request):
    identity = owner(request)
    data = project.model_dump()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        # Repeated identical submissions reuse the same workspace and consume no quota.
        previous = db.execute("SELECT id FROM projects WHERE owner=? AND data=?", (identity, json.dumps(data))).fetchone()
        if previous:
            return {"id": previous["id"]}
        consume(db, "global:" + day, DAILY_BUDGET)
        consume(db, "session:" + identity + day, SESSION_DAILY_LIMIT)
        # No trust in forwarded IP headers. Supplement with Turnstile before public deployment.
        ip = hashlib.sha256((request.client.host + day).encode()).hexdigest()
        consume(db, "ip:" + ip, IP_DAILY_LIMIT)
        extracted = db.execute("SELECT data FROM metadata_cache WHERE url=? AND created>?", (project.url,time.time()-21600)).fetchone() if project.url else None
        metadata = json.loads(extracted["data"]) if extracted else {}
        results = match(project, metadata)
        project_id = secrets.token_urlsafe(16)
        db.execute("INSERT INTO projects(id,owner,data,results,created) VALUES(?,?,?,?,?)",
                   (project_id, identity, json.dumps(data), json.dumps(results), time.time()))
    return {"id": project_id}


@app.get("/projects/{project_id}")
def get_project(project_id: str, request: Request):
    return project_response(project_id,request)


def project_response(project_id: str, request: Request, desktop: bool = False, on_progress=None, cached_only=False):
    row = owned(request, project_id)
    data, results = json.loads(row["data"]), json.loads(row["results"])
    if LIVE_SEARCH:
        from research_providers import configuration
        provider_enabled=configuration()['enabled']
        project = project_from_record(data)
        with connect() as db:
            metadata_row = db.execute('SELECT data FROM metadata_cache WHERE url=?', (project.url,)).fetchone() if project.url else None
        project = research_project(project, json.loads(metadata_row['data']) if metadata_row else {})
        key = hashlib.sha256((row["owner"]+str(SEARCH_VERSION)+cache_key(project)+provider_cache_signature()).encode()).hexdigest()
        if cached_only:
            with connect() as db:
                exists=db.execute('SELECT 1 FROM research_cache WHERE key=? AND created>?',(key,time.time()-21600)).fetchone()
            if not exists:return None
        with research_lock(key):
            with connect() as db:
                cached = db.execute("SELECT data FROM research_cache WHERE key=? AND created>?", (key,time.time()-21600)).fetchone()
                if cached_only and not cached:
                    return None
                if not cached:
                    day=time.strftime("%Y-%m-%d",time.gmtime())
                    db.execute("BEGIN IMMEDIATE")
                    for _ in range(0 if provider_enabled else 4):
                        consume(db,"public-search:"+day,SEARCH_DAILY_LIMIT)
            # Keep prior strong matches for this exact owner and product brief, across search versions.
            prior=results.get('discover',[])+results.get('conversations',[])
            with connect() as db:
                # The current version's expired cache is still valid candidate
                # evidence. Expiry requires fresh evaluation, not forgetting the
                # original posts and media we already retrieved for this brief.
                for version in range(2,SEARCH_VERSION+1):
                    for suffix in ("", provider_cache_signature()):
                        old_key=hashlib.sha256((row["owner"]+str(version)+cache_key(project)+suffix).encode()).hexdigest()
                        previous=db.execute("SELECT data FROM research_cache WHERE key=?",(old_key,)).fetchone()
                        if previous:
                            historic=json.loads(previous["data"])
                            prior.extend(historic.get("discover",[])+historic.get("conversations",[]))
            if cached:
                results=json.loads(cached["data"])
                if results.get('quality_report'):
                    from workspace_refresh import refresh
                    from research_routing import mode
                    results=refresh(project,results,previous_snapshot=json.loads(row['results']),native_only=desktop and mode()=='native')
            else:
                def charge_search():
                    with connect() as quota_db:
                        quota_db.execute('BEGIN IMMEDIATE')
                        consume(quota_db,'public-search:'+time.strftime('%Y-%m-%d',time.gmtime()),SEARCH_DAILY_LIMIT)
                try:
                    results=research_live(project, prior_candidates=prior,on_progress=on_progress,before_search=charge_search) if on_progress and provider_enabled else research_live(project, prior_candidates=prior,before_search=charge_search) if provider_enabled else research_live(project)
                except ResearchUnavailable as error:
                    raise HTTPException(503,str(error)) from None
                with connect() as db:
                    db.execute("INSERT OR REPLACE INTO research_cache VALUES(?,?,?)",(key,json.dumps(results),time.time()))
            from research_quality import select_results
            from live_discovery import revalidate_candidates
            from research_providers import configuration
            provider_config=configuration()
            from research_routing import mode
            candidates=results['discover']+results['conversations']+(prior if not provider_enabled else [])
            if desktop:
                candidates=without_restricted_previews(candidates)
            selected,report=select_results(project,revalidate_candidates(project,candidates),
                require_evaluation=provider_config['enabled'] and provider_config['evaluation'],native_only=desktop and mode()=='native')
            # Revalidation must not erase incomplete provider coverage and turn
            # a partial research session into a passing release audit.
            issues=results.get('research_issues',results.get('quality_report',{}).get('blockers',[]))
            if issues:
                report['launch_ready']=False
                report['blockers']=list(dict.fromkeys(report['blockers']+issues))
            results['discover']=[s for s in selected if s['section']=='discover']
            results['conversations']=[s for s in selected if s['section']=='conversations']
            for diagnostic in ('retrieval','evaluation_failures'):
                if diagnostic in results.get('quality_report',{}):report[diagnostic]=results['quality_report'][diagnostic]
            results['quality_report']=report
            results['coverage']={p:sum(s['platform']==p for s in selected) for p in ('Instagram','TikTok','Reddit','X')}
            for item in results["discover"]+results["conversations"]:
                item["author"]=author_label(item.get("author",""),item["platform"],item["url"])
            with connect() as db:
                from workspace_refresh import archive
                archive(db,project_id,json.loads(row['results']))
                db.execute("UPDATE projects SET results=? WHERE id=? AND owner=?",(json.dumps(results),project_id,row["owner"]))
    elif results.get("match_version") != 2:
        # Refresh old local matches on opening, without a new research charge or network call.
        project = project_from_record(data)
        with connect() as db:
            cached = db.execute("SELECT data FROM metadata_cache WHERE url=?", (project.url,)).fetchone() if project.url else None
            results = match(project, json.loads(cached["data"]) if cached else {})
            db.execute("UPDATE projects SET results=? WHERE id=? AND owner=?", (json.dumps(results), project_id, row["owner"]))
    from demo_access import demo_results
    return {"id": row["id"], "project": data, "results": results if desktop else demo_results(results),
            "published": bool(row["published"]), "rating": row["rating"],
            "review": {"public": bool(row["review_public"]), "text": row["review"] or "", "name": row["reviewer_name"]} if row["rating"] is not None else None}


# Local progressive jobs: only checked results are delivered, never raw candidates.
STREAM_JOBS={}
STREAM_LOCK=threading.Lock()

def _start_project_stream(project_id: str,request: Request,desktop=False):
    row=owned(request,project_id)
    identity=row['owner'];key=(identity,project_id)
    with STREAM_LOCK:
        current=STREAM_JOBS.get(key)
        if current and current['status']=='running':return {'status':'running'}
    # Persisted, current-policy research survives a service restart. Revalidate
    # it locally before creating a job; do not repeat network research on reopen.
    if LIVE_SEARCH:
        snapshot=project_response(project_id,request,cached_only=True,desktop=desktop)
        if snapshot is not None:
            with STREAM_LOCK:
                STREAM_JOBS[key]={'status':'complete','stage':'ready','started':time.time(),'workspace':snapshot,'revision':1}
            return {'status':'complete','workspace':snapshot}
    with STREAM_LOCK:
        # Completed snapshots can be reused briefly; failures are retryable.
        for old_key in list(STREAM_JOBS):
            if time.time()-STREAM_JOBS[old_key]['started']>600 and STREAM_JOBS[old_key]['status']!='running':STREAM_JOBS.pop(old_key)
        current=STREAM_JOBS.get(key)
        if current and current['status'] in ('running','complete'):return {'status':current['status']}
        if sum(job['status']=='running' for job in STREAM_JOBS.values())>=2:raise HTTPException(429,'Research is busy. Please try again shortly.')
        STREAM_JOBS[key]={'status':'running','stage':'preparing','started':time.time(),'workspace':None,'revision':0}
    def publish(partial):
        from demo_access import demo_results
        with STREAM_LOCK:
            STREAM_JOBS[key]['stage']=partial['stage']
            if partial.get('discover') or partial.get('conversations'):
                STREAM_JOBS[key]['revision']=STREAM_JOBS[key].get('revision',0)+1
                STREAM_JOBS[key]['workspace']={'id':project_id,'project':json.loads(row['data']),'published':bool(row['published']),'rating':row['rating'],'results':({**partial,'mode':'native_search','limit':60,'checked':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())} if desktop else demo_results({**partial,'mode':'live_search','limit':15,'checked':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}))}
    def run():
        try:
            result=project_response(project_id,request,on_progress=publish,desktop=desktop)
            with STREAM_LOCK:STREAM_JOBS[key].update(status='complete',stage='ready',workspace=result,revision=STREAM_JOBS[key].get('revision',0)+1)
        except Exception as error:
            message=error.detail if isinstance(error,HTTPException) and isinstance(error.detail,str) else 'Research could not finish. Your project is saved; please try again.'
            with STREAM_LOCK:STREAM_JOBS[key].update(status='failed',error=message)
    threading.Thread(target=run,daemon=True,name='outloud-research').start()
    return {'status':'running'}

@app.post('/projects/{project_id}/stream')
def start_project_stream(project_id: str,request: Request):
    return _start_project_stream(project_id,request)


@app.get('/projects/{project_id}/stream')
def project_stream(project_id: str,request: Request):
    row=owned(request,project_id)
    with STREAM_LOCK:
        job=STREAM_JOBS.get((row['owner'],project_id))
        if not job:raise HTTPException(404,'Start research for this project first.')
        return {key:value for key,value in job.items() if key!='started'}


@app.post("/desktop/research")
def desktop_research(project: Project, request: Request, identity: str = Depends(desktop_identity)):
    if not project.keywords:
        raise HTTPException(422, "Add research keywords: comma-separated words or phrases, up to 100 characters.")
    return research(project,request)


@app.get("/desktop/projects")
def desktop_projects(request: Request, identity: str = Depends(desktop_identity)):
    with connect() as db:
        rows=db.execute("SELECT id,data FROM projects WHERE owner=? ORDER BY created DESC",(identity,)).fetchall()
    return [{"id":row["id"],**json.loads(row["data"])} for row in rows]


@app.post("/desktop/projects/{project_id}/stream")
def start_desktop_stream(project_id: str,request: Request,identity: str = Depends(desktop_identity)):
    return _start_project_stream(project_id,request,desktop=True)


@app.get("/desktop/projects/{project_id}/stream")
def desktop_stream(project_id: str,request: Request,identity: str = Depends(desktop_identity)):
    return project_stream(project_id,request)


@app.get("/desktop/projects/{project_id}")
def desktop_project(project_id: str, request: Request, identity: str = Depends(desktop_identity)):
    return project_response(project_id,request,desktop=True)


@app.post("/projects/{project_id}/feedback")
def feedback(project_id: str, body: Feedback, request: Request):
    owned(request, project_id)
    with connect() as db:
        if not db.execute("SELECT reviewed FROM projects WHERE id=?", (project_id,)).fetchone()[0]:
            consume(db, "review:" + owner(request) + time.strftime("%Y-%m-%d"), 3)
        db.execute("UPDATE projects SET rating=?,review=?,reviewed=?,review_public=?,reviewer_name=?,reviewer_email=? WHERE id=?",
                   (body.rating, body.review.strip(), time.time(), int(body.public), body.reviewer_name.strip(), body.reviewer_email, project_id))
    return {"ok": True}


@app.delete("/projects/{project_id}/feedback")
def remove_feedback(project_id: str, request: Request):
    owned(request, project_id)
    with connect() as db:
        db.execute("UPDATE projects SET rating=NULL,review=NULL,reviewed=NULL,review_public=0,reviewer_name='',reviewer_email='' WHERE id=?", (project_id,))
    return {"ok": True}


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image = ""
        self.title = ""
        self.description = ""
        self.icon = ""
        self.icon_priority = 0
        self.in_title = False
        self.page_title = ""
        self.headings = []
        self.heading_tag = None
        self.heading_text = ""
        self.structured = []
        self.in_schema = False
        self.schema_text = ""
        self.subtitle = ""
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("h1", "h2") and len(self.headings)<12:
            self.heading_tag, self.heading_text = tag, ""
        if tag == "script" and attrs.get("type", "").lower()=="application/ld+json":
            self.in_schema, self.schema_text = True, ""
        if tag == "title":
            self.in_title = True
        if tag == "link":
            rel = attrs.get("rel", "").lower().split()
            priority = 2 if "apple-touch-icon" in rel else 1 if "icon" in rel else 0
            if priority > self.icon_priority and attrs.get("href"):
                self.icon, self.icon_priority = attrs["href"], priority
        if tag == "meta":
            key = attrs.get("property", attrs.get("name", "")).lower()
            value = attrs.get("content", "").strip()
            if key in ("og:site_name", "application-name"):
                self.subtitle = value[:180]
            if key == "og:image":
                self.image = value
            elif key == "og:title":
                self.title = value
            elif key == "og:description" or (key in ("description", "twitter:description") and not self.description):
                self.description = value
    def handle_endtag(self, tag):
        if tag == self.heading_tag:
            self.headings.append(clean(self.heading_text, 240))
            self.heading_tag = None
        if tag == "script" and self.in_schema:
            self.in_schema = False
            try:
                data = json.loads(self.schema_text)
                self.structured.extend(data if isinstance(data,list) else [data])
            except (ValueError, TypeError):
                pass
        if tag == "title":
            self.in_title = False
    def handle_data(self, data):
        if self.heading_tag:
            self.heading_text += data[:1000]
        if self.in_schema and len(self.schema_text)<32000:
            self.schema_text += data[:32000]
        if self.in_title:
            self.page_title += data



def structured_product(nodes):
    """Extract publisher-declared facts without executing scripts or following links."""
    pending = list(nodes)[:20]
    while pending:
        item = pending.pop(0)
        if not isinstance(item, dict):
            continue
        pending.extend(item.get("@graph", [])[:20] if isinstance(item.get("@graph"), list) else [])
        kinds = item.get("@type", [])
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if any(kind in ("SoftwareApplication", "MobileApplication", "WebApplication", "Product") for kind in kinds):
            offers = item.get("offers", {})
            offers = offers[0] if isinstance(offers, list) and offers else offers
            offers = offers if isinstance(offers, dict) else {}
            return {"name": clean(item.get("name"),120), "description": clean(item.get("description"),10000),
                    "category": clean(item.get("applicationCategory"),180),
                    "operating_system": clean(item.get("operatingSystem"),180),
                    "price": clean(offers.get("price"),80), "currency": clean(offers.get("priceCurrency"),12)}
    return {}


def social_profile_image(url, cover, nodes):
    parsed=urlsplit(url)
    host=(parsed.hostname or '').removeprefix('www.')
    parts=[part for part in parsed.path.split('/') if part]
    if host not in ('x.com','twitter.com','instagram.com','tiktok.com') or len(parts)!=1 or parts[0].lower() in ('p','reel','home','explore','login','accounts','search','i'):
        return ''
    pending=list(nodes)[:20]
    while pending:
        item=pending.pop(0)
        if not isinstance(item,dict):continue
        graph=item.get('@graph',[])
        if isinstance(graph,list):pending.extend(graph[:20])
        kind=item.get('@type')
        if kind=='Person' or isinstance(kind,list) and 'Person' in kind:
            image=item.get('image','')
            if isinstance(image,dict):image=image.get('url') or image.get('contentUrl','')
            if isinstance(image,str) and image:return safe_asset(urljoin(url,image))
    return safe_asset(cover) if cover else ''


def page_metadata(url):
    """Bounded HTTPS fetch pinned to a validated public IP to prevent SSRF/rebinding."""
    original = urlsplit(url)
    if original.hostname == "apps.apple.com":
        app_id = re.search(r"/id(\d+)", original.path)
        if app_id:
            country = original.path.strip("/").split("/")[0]
            country = country if re.fullmatch(r"[a-z]{2}", country) else "us"
            url = f"https://itunes.apple.com/lookup?id={app_id.group(1)}&country={country}"
    for _ in range(3):
        public_url(url)
        parsed = urlsplit(url)
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("Private address")
        address = addresses[0][4][0]
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=3)
        sock = socket.create_connection((address, 443), timeout=3)
        connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers={"User-Agent": "OutloudProjectPreview/0.1", "Accept": "text/html"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader("Location", ""))
                continue
            if response.status != 200:
                return {}
            content_type = response.getheader("Content-Type", "")
            if "json" in content_type or parsed.hostname == "itunes.apple.com":
                payload = json.loads(response.read(524288))
                item = (payload.get("results") or [{}])[0]
                return {"title": item.get("trackName", ""), "description": item.get("description", "")[:700],
                        "icon": safe_asset(item.get("artworkUrl512", item.get("artworkUrl100", ""))), "image": "",
                        "url": item.get("trackViewUrl", url), "method": "app_store_metadata",
                        "details": {"description": clean(item.get("description"), 10000), "categories": item.get("genres", [])[:8],
                        "screenshots": [safe_asset(u) for u in item.get("screenshotUrls", [])[:6]],
                        "languages": item.get("languageCodesISO2A", [])[:30], "price": item.get("formattedPrice", ""),
                        "developer": clean(item.get("artistName"), 180), "version": clean(item.get("version"), 80)},
                        "provenance": {"url": original.geturl(), "method": "app_store_metadata"}}
            if "text/html" not in content_type:
                return {}
            parser = MetadataParser()
            # Play places its metadata after roughly 1 MB of inline styling.
            # Keep a hard response bound while allowing its publisher facts to be reached.
            html_limit = 2097152 if parsed.hostname == "play.google.com" else 262144
            parser.feed(response.read(html_limit).decode("utf-8", errors="ignore"))
            cover = urljoin(url, parser.image) if parser.image else ""
            if cover:
                public_url(cover)
                host = urlsplit(cover).hostname
                if any(not ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)):
                    cover = ""
            product = structured_product(parser.structured)
            # Store publisher facts, never infer unsupported capabilities.
            description = re.sub(r"<[^>]*>", " ", parser.description or product.get("description", ""))
            description = re.sub(r"\s+", " ", description).strip()
            if len(description) > 700:
                description = description[:697].rsplit(" ", 1)[0] + "…"
            return {"image": cover, "profile_image": social_profile_image(url, cover, parser.structured), "title": (parser.title or parser.page_title).strip()[:120],
                    "description": description, "url": url, "method": "google_play_metadata" if parsed.hostname == "play.google.com" else "page_metadata",
                    "details": {"subtitle": parser.subtitle, "headings": parser.headings,
                                "product": product, "description": product.get("description", ""), "extracted_fields": [key for key,value in product.items() if value]},
                    "provenance": {"url": url, "method": "page_metadata"},
                    "icon": safe_asset(cover if parsed.hostname == "play.google.com" else urljoin(url, parser.icon or "/favicon.ico"))}
        finally:
            connection.close()
    return {}


def page_cover(url):
    return page_metadata(url).get("image", "")


class MetadataRequest(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        return public_url(value)


@app.post("/metadata")
def metadata(body: MetadataRequest, request: Request):
    identity = owner(request)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with connect() as db:
        consume(db, "metadata-attempt:" + identity + day, 100 if LOCAL_TESTING else 8)
        cached = db.execute("SELECT data FROM metadata_cache WHERE url=? AND created>?", (body.url, time.time()-21600)).fetchone()
        if cached:
            return json.loads(cached["data"])
        consume(db, "metadata-global:" + day, 500 if LOCAL_TESTING else 40)
    try:
        result = page_metadata(body.url)
    except (ValueError, OSError, UnicodeError, http.client.HTTPException):
        result = {}
    if len(result.get("description", "")) < 30:
        raise HTTPException(422, "We couldn’t read enough details from this link. Add a short description to continue.")
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata_cache VALUES(?,?,?)", (body.url, json.dumps(result), time.time()))
    return result


@app.post("/desktop/metadata")
def desktop_metadata(body: MetadataRequest, request: Request, identity: str = Depends(desktop_identity)):
    return metadata(body,request)


@app.post("/projects/{project_id}/preview")
def preview(project_id: str, body: Publication, request: Request):
    owned(request, project_id)
    image = ""
    icon = safe_asset(body.icon)
    if body.url:
        with connect() as db:
            consume(db, "preview:" + owner(request) + time.strftime("%Y-%m-%d"), 12 if LOCAL_TESTING else 5)
        try:
            details = page_metadata(body.url)
            image = details.get("image", "")
            icon = icon or details.get("icon", "")
        except (ValueError, OSError, http.client.HTTPException):
            pass  # A designed monogram cover works even without a website or accessible OG image.
    with connect() as db:
        db.execute("UPDATE projects SET cover=?,icon=?,preview_url=? WHERE id=?", (image, icon, body.url, project_id))
    return {"image": image, "icon": icon, "name": body.name.strip(), "description": body.description.strip(), "url": body.url}


@app.post("/projects/{project_id}/publish")
def publish(project_id: str, body: Publication, request: Request):
    row = owned(request, project_id)
    if not body.consent:
        raise HTTPException(400, "Choose to share your project before publishing.")
    data = json.loads(row["data"])
    if "<" in body.name + body.description or ">" in body.name + body.description:
        raise HTTPException(422, "Use plain text for your public project card.")
    card = {"id": project_id, "name": body.name.strip(), "description": body.description.strip(),
            "url": body.url, "platform": data["platform"], "status": data["status"],
            "image": row["cover"] if row["preview_url"] == body.url else "",
            "icon": safe_asset(body.icon) or (row["icon"] if row["preview_url"] == body.url else "")}
    # Public fields are deliberately separate from the private research brief and feedback.
    with connect() as db:
        db.execute("UPDATE projects SET published=1,consent_at=?,public_data=? WHERE id=?",
                   (time.time(), json.dumps(card), project_id))
    return {"ok": True}


@app.delete("/projects/{project_id}/publication")
def unpublish(project_id: str, request: Request):
    owned(request, project_id)
    with connect() as db:
        db.execute("UPDATE projects SET published=0,public_data=NULL,consent_at=NULL WHERE id=?", (project_id,))
    return {"ok": True}


@app.get("/gallery")
def gallery(limit: int = Query(24, ge=1, le=48), offset: int = Query(0, ge=0)):
    with connect() as db:
        rows = db.execute("SELECT public_data,rating,review_public FROM projects WHERE published=1 ORDER BY consent_at DESC,id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return [{**json.loads(row["public_data"]), "rating": row["rating"] if row["review_public"] else None} for row in rows]


@app.get("/gallery/count")
def gallery_count():
    with connect() as db:
        count = db.execute("SELECT COUNT(*) FROM projects WHERE published=1").fetchone()[0]
    return {"count": count}


@app.get("/reviews")
def public_reviews():
    with connect() as db:
        rows = db.execute("SELECT rating,review,reviewer_name FROM projects WHERE review_public=1 AND rating IS NOT NULL ORDER BY reviewed DESC").fetchall()
        aggregate = db.execute("SELECT COUNT(*),AVG(rating) FROM projects WHERE review_public=1 AND rating IS NOT NULL").fetchone()
    return {"count": aggregate[0], "average": round(aggregate[1], 1) if aggregate[1] else None,
            "reviews": [{"rating": row["rating"], "text": row["review"], "name": row["reviewer_name"] or "A visiting developer"} for row in rows]}


# Local evaluation analytics: anonymous session IDs and allowlisted events only.
ANALYTICS_EVENTS = {"page_view", "trial_clicked", "workflow_clicked", "new_project", "trial_stage", "research_started", "research_completed", "research_failed", "reference_opened", "source_clicked", "feedback_opened", "preorder_clicked", "page_exit", "review_submitted", "project_published", "section_view"}
ANALYTICS_STEPS = {"", "landing", "welcome", "setup", "loading", "workspace", "gallery", "discover", "conversations", "hero", "workflow", "trial-entry", "reviews", "pricing", "download", "faq", "reference"}

class AnalyticsEvent(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    session: str = Field(pattern=r"^[a-f0-9-]{36}$")
    event: str
    step: str = ""
    path: str

    @field_validator("event")
    @classmethod
    def event_allowed(cls, value):
        if value not in ANALYTICS_EVENTS:
            raise ValueError("Unknown event")
        return value

    @field_validator("step")
    @classmethod
    def step_allowed(cls, value):
        if value not in ANALYTICS_STEPS:
            raise ValueError("Unknown step")
        return value

    @field_validator("path")
    @classmethod
    def path_allowed(cls, value):
        if value not in {"landing", "trial"}:
            raise ValueError("Unknown page")
        return value


def analytics_table(db):
    db.execute("CREATE TABLE IF NOT EXISTS analytics_events (id TEXT PRIMARY KEY, session TEXT NOT NULL, event TEXT NOT NULL, step TEXT NOT NULL, path TEXT NOT NULL, created REAL NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS analytics_created ON analytics_events(created)")


@app.post("/analytics/events", status_code=202)
def record_analytics(payload: AnalyticsEvent):
    with connect() as db:
        analytics_table(db)
        db.execute("DELETE FROM analytics_events WHERE created < ?", (time.time()-30*86400,))
        count=db.execute("SELECT COUNT(*) FROM analytics_events WHERE session=? AND created>?", (payload.session,time.time()-3600)).fetchone()[0]
        if count >= 300:
            raise HTTPException(429,"Event limit reached")
        db.execute("INSERT OR IGNORE INTO analytics_events VALUES (?,?,?,?,?,?)", (payload.id,payload.session,payload.event,payload.step,payload.path,time.time()))
    return {"accepted":True}


@app.get("/analytics/summary")
def analytics_summary():
    with connect() as db:
        analytics_table(db)
        rows=db.execute("SELECT event, COUNT(*) events, COUNT(DISTINCT session) sessions FROM analytics_events GROUP BY event ORDER BY events DESC").fetchall()
        stages=db.execute("SELECT step,COUNT(DISTINCT session) sessions FROM analytics_events WHERE event='trial_stage' GROUP BY step").fetchall()
        exits=db.execute("SELECT step,COUNT(DISTINCT session) sessions FROM analytics_events WHERE event='page_exit' GROUP BY step").fetchall()
        last=db.execute("SELECT step,COUNT(*) sessions FROM (SELECT step,ROW_NUMBER() OVER (PARTITION BY session ORDER BY created DESC,id DESC) n FROM analytics_events) WHERE n=1 GROUP BY step").fetchall()
    return {"events":[dict(row) for row in rows],"stages":[dict(row) for row in stages],"exits":[dict(row) for row in exits],"last_seen":[dict(row) for row in last],"retention_days":30}


@app.api_route("/commerce/{action}", methods=["GET", "POST"])
async def local_commerce_proxy(action: str, request: Request):
    # Dev-only bridge to the existing checkout. No Stripe secrets in the browser.
    # A purchase is real: only manually completing Stripe can charge a card.
    if not LOCAL_TESTING:
        raise HTTPException(404)
    allowed={"pricing":"GET","availability":"GET","start":"POST","cancel":"POST","license":"GET"}
    if allowed.get(action)!=request.method:
        raise HTTPException(404)
    import httpx
    headers={"Origin":"https://tryoutloud.pages.dev","Content-Type":"application/json"}
    if request.headers.get("cookie"):
        headers["Cookie"]=request.headers["cookie"]
    try:
        async with httpx.AsyncClient(timeout=25,follow_redirects=False) as client:
            upstream=await client.request(request.method,"https://tryoutloud.pages.dev/api/purchase/"+action,headers=headers,params=request.query_params,content=b"{}" if request.method=="POST" else None)
        if "application/json" not in upstream.headers.get("content-type",""):
            raise HTTPException(502,"Checkout is temporarily unavailable. Please try again.")
        response=Response(content=upstream.content,status_code=upstream.status_code,media_type="application/json")
        for cookie in upstream.headers.get_list("set-cookie"):
            response.headers.append("set-cookie",cookie)
        return response
    except httpx.HTTPError:
        raise HTTPException(503,"Checkout is temporarily unavailable. Please try again.")


THUMBNAIL_LOCK = threading.Lock()

TIKTOK_COVER_CACHE = 'tiktok-cover-v3:'


def without_restricted_previews(candidates):
    keys = {'thumbnail:' + TIKTOK_COVER_CACHE + source['url']: source['url']
            for source in candidates if source.get('platform') == 'TikTok' and source.get('url')}
    if not keys:
        return candidates
    with connect() as db:
        placeholders = ','.join('?' for _ in keys)
        rows = db.execute(f'SELECT key,data FROM research_cache WHERE key IN ({placeholders}) AND created>?',
                          (*keys, time.time()-1800)).fetchall()
    restricted = {keys[row['key']] for row in rows if json.loads(row['data']).get('unavailable') is True}
    return [source for source in candidates if source.get('url') not in restricted]


@app.get('/sources/thumbnail')
def source_thumbnail(request: Request, url: str = Query(max_length=600)):
    return get_source_preview(request, url)


def get_source_preview(request, url, include_video=False, *, desktop=False):
    from live_discovery import fetch_post_preview, fetch_thumbnail, post_identity
    identity=owner(request)
    post=post_identity(url)
    if not post:raise HTTPException(400,'Unsupported source.')
    # Only retrieve previews for posts already returned to this visitor.
    with connect() as db:
        rows=db.execute('SELECT results FROM projects WHERE owner=?',(identity,)).fetchall()
    if not any(s.get('url')==url for row in rows for s in (json.loads(row['results']).get('discover',[])+json.loads(row['results']).get('conversations',[]))):
        raise HTTPException(404,'Reference not found in your projects.')
    key=('media-preview:' if include_video else 'thumbnail:')+(TIKTOK_COVER_CACHE if post[0]=='TikTok' else '')+url
    with THUMBNAIL_LOCK:
        with connect() as db:
            cached=db.execute('SELECT data FROM research_cache WHERE key=? AND created>?',(key,time.time()-1800)).fetchone()
            if cached:return json.loads(cached['data'])
            if desktop:
                # Signed covers can expire repeatedly during a normal workspace session.
                consume(db,'desktop-thumbnail:'+identity+':'+time.strftime('%Y-%m-%dT%H',time.gmtime()),100)
            else:
                consume(db,'thumbnail:'+identity+':'+time.strftime('%Y-%m-%d',time.gmtime()),100)
        result=fetch_post_preview(url) if include_video or post[0]=='TikTok' else {'thumbnail':fetch_thumbnail(url)}
        with connect() as db:db.execute('INSERT OR REPLACE INTO research_cache VALUES(?,?,?)',(key,json.dumps(result),time.time()))
    return result


class SourcePreviewRequest(BaseModel):
    url: str = Field(min_length=10, max_length=600)
    include_video: bool = False


@app.post('/desktop/sources/thumbnail')
def desktop_source_thumbnail(body: SourcePreviewRequest, request: Request, identity: str = Depends(desktop_identity)):
    return get_source_preview(request, body.url, body.include_video, desktop=True)
