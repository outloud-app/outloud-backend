"""Meaningful API checks: consent, isolation, limits and public/private separation."""
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
import app as module

HEADERS = {"Origin": "http://127.0.0.1:4321"}
BRIEF = {"name": "Small Steps", "platform": "iOS", "status": "unlaunched", "url": "",
         "description": "A private habit tracker for people who quit after missing a day. PRIVATE-BRIEF",
         "category": "habits"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB", tmp_path / "trial.sqlite3")
    with TestClient(module.app, headers=HEADERS) as client:
        assert client.post("/session").status_code == 200
        yield client


def create(client, **changes):
    response = client.post("/research", json={**BRIEF, **changes})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_private_projects_and_results_are_isolated(client):
    project = create(client)
    data = client.get(f"/projects/{project}").json()
    assert len(data["results"]["discover"]) + len(data["results"]["conversations"]) <= 10
    assert all(item["section"] == "conversations" for item in data["results"]["conversations"])
    assert client.get("/gallery").json() == []
    with TestClient(module.app, headers=HEADERS) as stranger:
        stranger.post("/session")
        assert stranger.get(f"/projects/{project}").status_code == 404
        assert stranger.post(f"/projects/{project}/publish", json={"consent": True, "name": "Stolen", "description": "This is not my project or brief."}).status_code == 404


def test_publication_requires_consent_and_exposes_only_public_fields(client):
    project = create(client)
    client.post(f"/projects/{project}/feedback", json={"rating": 4, "review": "PRIVATE-REVIEW"})
    body = {"consent": False, "name": "Small Steps", "description": "Build a smaller habit. Start again tomorrow.", "url": ""}
    assert client.post(f"/projects/{project}/publish", json=body).status_code == 400
    assert client.post(f"/projects/{project}/publish", json={**body, "consent": True}).status_code == 200
    gallery = client.get("/gallery")
    assert len(gallery.json()) == 1
    assert "PRIVATE-BRIEF" not in gallery.text and "PRIVATE-REVIEW" not in gallery.text
    assert "owner" not in gallery.text and gallery.json()[0]["rating"] is None
    assert client.delete(f"/projects/{project}/publication").status_code == 200
    assert client.get("/gallery").json() == []


def test_duplicate_submission_is_idempotent_and_cap_is_atomic(client):
    original = create(client)
    assert create(client) == original
    create(client, name="Second app")
    create(client, name="Third app")
    assert client.post("/research", json={**BRIEF, "name": "Fourth app"}).status_code == 429
    assert client.get(f"/projects/{original}").status_code == 200
    with module.connect() as db:
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0] == 3
        assert db.execute("SELECT hits FROM limits WHERE key LIKE 'global:%'").fetchone()[0] == 3


def test_niche_mismatch_returns_empty_not_unrelated_results(client):
    project = create(client, category="other", description="A tool for theatre stage managers to synchronise lighting cues.")
    results = client.get(f"/projects/{project}").json()["results"]
    assert results["discover"] == [] and results["conversations"] == []


def test_private_urls_and_other_origins_are_rejected(client):
    for url in ("https://127.0.0.1/", "ftp://example.com", "https://localhost/", "https://example.com:8766/"):
        assert client.post("/research", json={**BRIEF, "url": url}).status_code == 422
    assert client.post("/session", headers={"Origin": "https://not-outloud.test"}).status_code == 403


def test_metadata_pins_public_addresses_and_handles_private_redirects(client, monkeypatch):
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError):
        module.page_cover("https://example.com")


def test_feedback_does_not_implicitly_publish(client):
    project = create(client)
    assert client.post(f"/projects/{project}/feedback", json={"rating": 6}).status_code == 422
    assert client.post(f"/projects/{project}/feedback", json={"rating": 5, "review": "Useful references"}).status_code == 200
    assert client.get("/gallery").json() == []


def test_description_matching_changes_category_and_results(client):
    habit = create(client, category="auto")
    finance = create(client, category="auto", name="Pocket Budget", description="A budgeting app for students to manage spending and track expenses and savings.")
    a = client.get(f"/projects/{habit}").json()["results"]
    b = client.get(f"/projects/{finance}").json()["results"]
    assert a["category"] == "habits" and b["category"] == "finance"
    assert not set(item["id"] for item in a["discover"]) & set(item["id"] for item in b["discover"])


def test_metadata_parser_reads_title_and_description():
    parser = module.MetadataParser()
    parser.feed('<title>Fallback title</title><meta name="description" content="A clear description of a budgeting product."><meta property="og:title" content="Pocket Budget"><meta property="og:image" content="https://example.com/cover.png">')
    assert parser.title == "Pocket Budget"
    assert parser.description == "A clear description of a budgeting product."
    assert parser.image == "https://example.com/cover.png"


def test_metadata_is_cached_and_rejects_empty_descriptions(client, monkeypatch):
    calls = []
    def fetch(url):
        calls.append(url)
        return {"title": "Budget", "description": "A budgeting app that helps students understand their spending.", "image": "", "url": url}
    monkeypatch.setattr(module, "page_metadata", fetch)
    for _ in range(2):
        response = client.post("/metadata", json={"url": "https://example.com/"})
        assert response.status_code == 200
        assert response.json()["title"] == "Budget"
    assert len(calls) == 1
    monkeypatch.setattr(module, "page_metadata", lambda url: {})
    assert client.post("/metadata", json={"url": "https://example.com/no-metadata"}).status_code == 422
    assert client.post("/metadata", json={"url": "https://127.0.0.1/"}).status_code == 422


def test_only_explicit_public_reviews_are_public(client):
    project = create(client)
    client.post(f"/projects/{project}/feedback", json={"rating": 4, "review": "Old private feedback"})
    assert client.get("/reviews").json()["count"] == 0
    client.post(f"/projects/{project}/feedback", json={"rating": 5, "review": "Useful references", "public": True, "reviewer_name": "Alex"})
    result = client.get("/reviews").json()
    assert result["count"] == 1 and result["average"] == 5
    assert result["reviews"] == [{"rating": 5, "text": "Useful references", "name": "Alex"}]
    assert "PRIVATE-BRIEF" not in json.dumps(result)
    assert client.get("/gallery").json() == []
    assert client.delete(f"/projects/{project}/feedback").status_code == 200
    assert client.get("/reviews").json()["count"] == 0


def test_expanded_categories_and_preferred_site_icon(client):
    assert len(module.CATEGORIES) >= 35
    project = create(client, category="weather", description="Local weather forecasts for people who commute to work by bike.")
    assert client.get(f"/projects/{project}").json()["results"]["discover"] == []
    parser = module.MetadataParser()
    parser.feed('<link rel="icon" href="/favicon.ico"><link rel="apple-touch-icon" href="/app-icon.png"><link rel="icon" href="/favicon-16.png">')
    assert parser.icon == "/app-icon.png"


def test_bare_domains_are_normalized_without_weakening_network_checks(client):
    assert module.public_url("instagram.com") == "https://instagram.com"
    assert module.public_url(" www.instagram.com/profile ") == "https://www.instagram.com/profile"
    assert module.public_url("http://example.com/app") == "https://example.com/app"
    for url in ("localhost", "127.0.0.1", "javascript:alert(1)"):
        assert client.post("/metadata", json={"url": url}).status_code == 422


def test_developer_allowance_accepts_six_and_reuses_existing_projects(client, monkeypatch):
    monkeypatch.setattr(module, "SESSION_DAILY_LIMIT", 6)
    first = create(client, name="Developer app 1")
    for i in range(2, 7):
        create(client, name=f"Developer app {i}")
    assert create(client, name="Developer app 1") == first
    assert client.post("/research", json={**BRIEF, "name": "Developer app 7"}).status_code == 429


def test_gallery_paginates_all_published_projects_without_exposing_private_rows(client):
    original = create(client)
    with module.connect() as db:
        for index in range(25):
            public = {"id": f"public-{index:02}", "name": f"App {index}", "description": "A useful public app.", "url": "", "platform": "iOS", "status": "unlaunched"}
            db.execute("INSERT INTO projects(id,owner,data,results,created,published,consent_at,public_data) VALUES(?,?,?,?,?,1,?,?)",
                       (public["id"], "fixture-owner", "{}", "{}", index, index, json.dumps(public)))
    assert client.get("/gallery/count").json() == {"count": 25}
    assert len(client.get("/gallery?limit=6").json()) == 6
    first = client.get("/gallery").json()
    last = client.get("/gallery?offset=24").json()
    assert len(first) == 24 and len(last) == 1
    assert len({row["id"] for row in first + last}) == 25
    assert original not in {row["id"] for row in first + last}
    assert client.get("/gallery?limit=1000").status_code == 422
    assert client.get("/gallery?offset=-1").status_code == 422


def test_review_email_is_private_validated_and_deleted_with_review(client):
    project = create(client)
    body = {"rating": 4, "review": "Useful references", "public": True, "reviewer_name": "Pat", "reviewer_email": " pat@example.com "}
    assert client.post(f"/projects/{project}/feedback", json=body).status_code == 200
    with module.connect() as db:
        assert db.execute("SELECT reviewer_email FROM projects WHERE id=?", (project,)).fetchone()[0] == "pat@example.com"
    for path in ("/reviews", "/gallery", "/gallery/count", "/projects", f"/projects/{project}"):
        response = client.get(path)
        assert "pat@example.com" not in response.text
        assert "reviewer_email" not in response.text
    assert client.post(f"/projects/{project}/feedback", json={**body, "reviewer_email": "bad-email"}).status_code == 422
    assert client.delete(f"/projects/{project}/feedback").status_code == 200
    with module.connect() as db:
        assert db.execute("SELECT reviewer_email FROM projects WHERE id=?", (project,)).fetchone()[0] == ""


def test_auto_category_covers_imported_social_and_screen_time_details(client):
    social = module.Project(**{**BRIEF, "name": "Discord", "category": "auto", "description": "Group chat with friends. Build social communities, meet people and talk in your community."})
    focus = module.Project(**{**BRIEF, "name": "Brain Rot", "category": "auto", "description": "Reduce screen-time and block distractions so you can focus on your daily tasks."})
    assert module.match(social)["category"] == "social"
    assert module.match(focus)["category"] == "productivity"
    assert module.match(social)["discover"] == []  # No fabricated catalog coverage.


def test_owner_can_recognize_review_and_publication_without_leaking_contact(client):
    project = create(client)
    client.post(f"/projects/{project}/feedback", json={"rating": 5, "review": "A useful starting point", "public": True, "reviewer_name": "Sam", "reviewer_email": "private@example.com"})
    body = {"consent": True, "name": "Small Steps", "description": "Build a smaller habit. Start again tomorrow.", "url": ""}
    assert client.post(f"/projects/{project}/publish", json=body).status_code == 200
    state = client.get(f"/projects/{project}").json()
    assert state["published"] is True
    assert state["review"] == {"public": True, "text": "A useful starting point", "name": "Sam"}
    assert "private@example.com" not in json.dumps(state)
    client.delete(f"/projects/{project}/publication")
    state = client.get(f"/projects/{project}").json()
    assert state["published"] is False and state["review"]["public"] is True


def test_discovery_and_conversations_have_distinct_source_types(client):
    for category in ('habits', 'finance', 'developer', 'learning', 'fitness'):
        result = module.match(module.Project(**{**BRIEF, 'category': category}))
        discovery, conversations = result['discover'], result['conversations']
        assert all(row['kind'] != 'Discussion' for row in discovery)
        assert all(row['kind'] == 'Discussion' for row in conversations)
        assert not {row['id'] for row in discovery} & {row['id'] for row in conversations}


def test_all_owned_projects_are_available_for_switching(client, monkeypatch):
    monkeypatch.setattr(module, 'SESSION_DAILY_LIMIT', 20)
    for index in range(11):
        create(client, name=f'Project {index}')
    assert len(client.get('/projects').json()) == 11


def test_anonymous_analytics_deduplicates_and_validates(client):
    event={"id":"11111111-1111-4111-8111-111111111111","session":"22222222-2222-4222-8222-222222222222","event":"trial_clicked","step":"landing","path":"landing"}
    assert client.post("/analytics/events",json=event).status_code==202
    assert client.post("/analytics/events",json=event).status_code==202
    result=client.get("/analytics/summary").json()
    assert result["events"]==[{"event":"trial_clicked","events":1,"sessions":1}]
    assert client.post("/analytics/events",json={**event,"step":"private app description"}).status_code==422
    assert client.post("/analytics/events",json={**event,"event":"arbitrary"}).status_code==422
    assert client.post("/analytics/events",json={**event,"path":"https://private.example"}).status_code==422
    with TestClient(module.app,headers={"Origin":"https://unrelated.example"}) as stranger:
        assert stranger.post("/analytics/events",json=event).status_code==403


def test_local_commerce_bridge_is_allowlisted_and_preserves_json(client,monkeypatch):
    import httpx
    monkeypatch.setattr(module,"LOCAL_TESTING",True)
    captured={}
    class Upstream:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def request(self,method,url,**options):
            captured.update(method=method,url=url,**options)
            return httpx.Response(200,json={"environment":"live","url":"https://checkout.stripe.com/example"},headers={"set-cookie":"checkout=test; Secure; HttpOnly"})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:Upstream())
    result=client.post("/commerce/start",json={"currency":"cheaper"})
    assert result.status_code==200
    assert captured["url"]=="https://tryoutloud.pages.dev/api/purchase/start"
    assert captured["headers"]["Origin"]=="https://tryoutloud.pages.dev"
    assert captured["content"]==b"{}"
    assert "HttpOnly" in result.headers["set-cookie"]
    assert client.post("/commerce/arbitrary",json={}).status_code==404
    monkeypatch.setattr(module,"LOCAL_TESTING",False)
    assert client.post("/commerce/start",json={}).status_code==404


def test_local_commerce_html_error_is_not_exposed_as_json_parse_error(client,monkeypatch):
    import httpx
    monkeypatch.setattr(module,"LOCAL_TESTING",True)
    class Upstream:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def request(self,*args,**kwargs):return httpx.Response(502,text="<!DOCTYPE html>oops",headers={"content-type":"text/html"})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:Upstream())
    response=client.post("/commerce/start",json={})
    assert response.status_code==502
    assert response.json()=={"detail":"Checkout is temporarily unavailable. Please try again."}


def test_product_context_is_private_and_survives_reopening(client):
    project = create(client, audience='People rebuilding routines', problem='Giving up after one missed day', features=['Flexible habit goals', 'Keep your progress'])
    workspace = client.get(f'/projects/{project}').json()
    assert workspace['project']['audience']=='People rebuilding routines'
    assert workspace['results']['profile']['features']==['Flexible habit goals','Keep your progress']
    assert workspace['results']['profile']['confirmed'] is True
    assert all('match_reason' in item and item['matched_terms'] for item in workspace['results']['discover']+workspace['results']['conversations'] if not item.get('locked'))
    assert client.get('/gallery').json()==[]


def test_category_alone_does_not_qualify_results():
    project = module.Project(**{**BRIEF, 'name':'Quantum Orchard', 'description':'An agricultural mapping utility for remote orchard surveying.', 'category':'habits'})
    result = module.match(project)
    assert result['discover']==[] and result['conversations']==[]


def test_matching_uses_confirmed_features_and_remains_bounded():
    project = module.Project(**{**BRIEF, 'features':['Meditation and mindfulness', 'Habit consistency']})
    result=module.match(project)
    assert len(result['discover'])+len(result['conversations'])<=10
    assert all(not item['evidence']['engagement_verified'] for item in result['discover']+result['conversations'])
    assert 'meditation' in result['profile']['keywords']


def test_parser_collects_headings_and_structured_product_without_script_execution():
    parser=module.MetadataParser()
    parser.feed('''<h1>Plan home-cooked meals</h1><h2>Quick ingredient logging</h2><script type="application/ld+json">{"@graph":[{"@type":"SoftwareApplication","name":"Meal Log","description":"Track homemade meals without weighing every ingredient.","applicationCategory":"HealthApplication","offers":{"price":"4.99","priceCurrency":"USD"}}]}</script><script>throw new Error("not executed")</script>''')
    assert parser.headings==['Plan home-cooked meals','Quick ingredient logging']
    product=module.structured_product(parser.structured)
    assert product['name']=='Meal Log'
    assert product['price']=='4.99'
    assert product['currency']=='USD'


def test_research_uses_cached_extraction_without_new_network_request(client):
    url='https://example.com/habits'
    metadata={'details':{'headings':['Meditation and mindfulness practice']}, 'provenance':{'url':url,'method':'page_metadata'}}
    import time
    with module.connect() as db:
        db.execute('INSERT INTO metadata_cache VALUES(?,?,?)',(url,json.dumps(metadata),time.time()))
    project=create(client,url=url)
    profile=client.get(f'/projects/{project}').json()['results']['profile']
    assert profile['public_details']['headings']==['Meditation and mindfulness practice']
    assert profile['provenance']['url']==url


def test_trading_product_does_not_receive_budgeting_references(client):
    project=create(client,name='Watchers',description='A trading analysis app for forex and cryptocurrency traders. Instead of spending hours monitoring charts, receive alerts for chart patterns and trading setups.',audience='Forex and crypto traders',features=['Candlestick pattern detection','Market scanning'])
    result=client.get(f'/projects/{project}').json()['results']
    assert result['discover']==[] and result['conversations']==[]


def test_older_matches_refresh_without_consuming_research_quota(client):
    project=create(client)
    with module.connect() as db:
        db.execute('UPDATE projects SET results=? WHERE id=?',(json.dumps({'discover':[], 'conversations':[]}),project))
        before=[tuple(row) for row in db.execute('SELECT key,hits FROM limits ORDER BY key')]
    result=client.get(f'/projects/{project}').json()['results']
    assert result['match_version']==2
    with module.connect() as db:
        assert before==[tuple(row) for row in db.execute('SELECT key,hits FROM limits ORDER BY key')]


def test_diversity_never_inserts_an_unrelated_platform():
    from product_profile import rank_catalog
    project=module.Project(**{**BRIEF,'description':'A habit tracker for restarting routines after missed streaks.'})
    def source(id,platform,keys):
        return {'id':id,'platform':platform,'kind':'Post','title':'Reference','summary':'Reference','keywords':keys,'categories':['habits'],'section':'discover'}
    catalog=[source('a','Instagram',['habit','streaks']),source('b','TikTok',['habit','restarting']),source('c','X',['cooking','recipes'])]
    results=rank_catalog(project,catalog,module.CATEGORY_KEYWORDS)['discover']
    assert {item['platform'] for item in results}=={'Instagram','TikTok'}


def test_play_metadata_after_large_style_block_is_extracted(monkeypatch):
    from types import SimpleNamespace
    body = ("<style>" + " " * 1000000 + "</style>"
            '<meta property="og:title" content="A real app">'
            '<meta property="og:description" content="Help people organise their meals and plan a weekly grocery list.">'
            '<meta property="og:image" content="https://play-lh.googleusercontent.com/product-icon">').encode()
    class Reply:
        status = 200
        def getheader(self, name, default=""):
            return "text/html" if name == "Content-Type" else default
        def read(self, limit):
            assert limit <= 2097152
            return body[:limit]
    class Connection:
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Reply()
        def close(self): pass
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(module.socket, "create_connection", lambda *args, **kwargs: object())
    monkeypatch.setattr(module.ssl, "create_default_context", lambda: SimpleNamespace(wrap_socket=lambda *args, **kwargs: object()))
    monkeypatch.setattr(module.http.client, "HTTPSConnection", lambda *args, **kwargs: Connection())
    metadata = module.page_metadata("https://play.google.com/store/apps/details?id=example.app")
    assert metadata["title"] == "A real app"
    assert "grocery list" in metadata["description"]
    assert metadata["icon"] == "https://play-lh.googleusercontent.com/product-icon"
    assert metadata["method"] == "google_play_metadata"
