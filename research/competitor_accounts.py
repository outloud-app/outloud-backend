"""Project-scoped publisher verification and bounded native profile collection."""
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit

import httpx
from research_retrieval import connect

PLATFORMS={
    'TikTok':('clockworks~tiktok-scraper', 'www.tiktok.com', 500_000),
    'Instagram':('apify~instagram-scraper', 'www.instagram.com', 100_000),
    'X':('pro100chok~x-twitter-all-in-one-scraper', 'x.com', 10_000),
}
PROFILE_TTL=3*86400
_HANDLE=re.compile(r'[A-Za-z0-9_.]{1,30}')


def brand(value):
    return re.sub(r'[^a-z0-9]','',str(value).casefold())


def profile(value):
    try:
        url=urlsplit(value)
        port=url.port
    except ValueError:
        return None
    if url.scheme!='https' or url.username or url.password or port not in (None,443):return None
    host=(url.hostname or '').removeprefix('www.')
    platform=next((p for p,(_,domain,_) in PLATFORMS.items() if domain.removeprefix('www.')==host),None)
    handle=url.path.strip('/').removeprefix('@')
    if not platform or not _HANDLE.fullmatch(handle) or handle.casefold() in {'search','explore','home','login','i','p','reel'}:return None
    if platform=='TikTok' and not url.path.startswith('/@'):return None
    return platform,handle.casefold()


def official_handle(row, name, domain=None):
    identity=row.get('authorMeta') or row.get('author') or row
    if not isinstance(identity,dict):return None
    handle=identity.get('uniqueId') or identity.get('username') or identity.get('screen_name') or identity.get('userName')
    if not handle and identity is row.get('authorMeta'):handle=identity.get('name')
    if not isinstance(handle,str) or not _HANDLE.fullmatch(handle):return None
    display=identity.get('fullName') or identity.get('nickname') or identity.get('displayName') or identity.get('name') or ''
    if brand(name) not in {brand(handle),brand(display)}:return None
    links=[]
    entities=identity.get('entities') or {}
    if isinstance(entities,dict):
        for field in ('url','description'):
            entity=entities.get(field) or {}
            if isinstance(entity,dict):
                links.extend(item['expanded_url'] for item in (entity.get('urls') or []) if isinstance(item,dict)
                             and isinstance(item.get('expanded_url'),str) and item['expanded_url'].startswith('https://'))
    for key in ('externalUrl','url','expandedUrl','bioLink','bioUrl','website','description','biography','signature','bio'):
        value=identity.get(key)
        if isinstance(value,dict):value=value.get('link') or value.get('expanded_url')
        if isinstance(value,str):links.extend(re.findall(r'https://[^\s<>"]+',value))
    for link in links:
        link=urlsplit(link.rstrip('.,)'))
        if link.username or link.password:continue
        hostname=(link.hostname or '').removeprefix('www.')
        path_tokens={brand(re.sub(r'^id\d+$','',part)) for part in link.path.split('/')}
        if hostname in ('apps.apple.com','play.google.com','marketplace.microsoft.com'):
            identifiers=re.findall(r'(?:[?&]id=)([a-zA-Z0-9_.]+)',link.query and '?'+link.query)
            if brand(name) in path_tokens or any(brand(name) in {brand(part) for part in value.split('.')} for value in identifiers):
                return handle.casefold()
        elif hostname==domain or (not domain and hostname.count('.')==1
                                  and len(brand(name))>=4 and brand(hostname.split('.')[0])==brand(name)):
            return handle.casefold()
    return None


def source_handle(source):
    if source['platform'] in ('TikTok','X'):
        path=urlsplit(source['url']).path.strip('/').split('/')
        if len(path)>=3 and path[1] in ('status','video') and _HANDLE.fullmatch(path[0].removeprefix('@')):
            return path[0].removeprefix('@').casefold()
    return str(source.get('author','')).removeprefix('@').casefold()


def actor_input(platform,target,posts):
    if platform=='TikTok':
        if posts:
            return {'profiles':[target],'resultsPerPage':20,'excludePinnedPosts':True,'shouldDownloadVideos':False,'shouldDownloadCovers':False}
        return {'searchQueries':[target],'searchSection':'/user','maxProfilesPerQuery':5,'shouldDownloadVideos':False}
    if platform=='Instagram':
        if posts:return {'username':[target],'resultsLimit':20,'onlyPostsNewerThan':'12 months','skipPinnedPosts':True}
        return {'search':target,'searchType':'profile','searchLimit':5,'resultsType':'details'}
    return {'scrapeType':'userPosts' if posts else 'search','targets':[target],
            'maxItems':20 if posts else 5,'searchType':'latest','excludeReposts':True,
            'findEmails':False,'includeAbout':False}


def collect(platform,target,posts):
    from native_access import require,actor_start
    from research_providers import authorize,cached_collection,collect_media_run,MediaPending
    actor,_,cap=PLATFORMS[platform]
    if platform=='Instagram' and posts:
        actor='apify~instagram-reel-scraper'
    payload=actor_input(platform,target,posts)
    limit=20 if posts else 5
    path=os.environ.get('OUTLOUD_PROVIDER_CACHE',os.path.join(os.path.dirname(__file__),'.data/provider-media.sqlite3'))
    from native_conversations import credential_fingerprint
    fingerprint=credential_fingerprint()
    key='competitor-account-v1:'+hashlib.sha256(json.dumps([actor,payload],sort_keys=True).encode()).hexdigest()
    if fingerprint:key+=':'+fingerprint
    def start():
        require()
        authorize('apify-competitor-account-'+platform.lower(),cap)
        data=actor_start(httpx.post,'https://api.apify.com/v2/acts/'+actor+'/runs',json=payload,
            headers={'Authorization':'Bearer '+os.environ['APIFY_TOKEN']},
            params={'maxTotalChargeUsd':cap/1e6,'maxItems':limit,'timeout':90},timeout=15)
        return {'run_id':data['id'],'dataset_id':data['defaultDatasetId']}
    run,rows,observed=cached_collection(key,path,start,max_age=PROFILE_TTL if posts else None,empty_max_age=PROFILE_TTL)
    if rows is None:
        deadline=time.monotonic()+35
        while True:
            try:rows=collect_media_run(run);break
            except MediaPending:
                if time.monotonic()>=deadline:raise
                time.sleep(1)
        import sqlite3
        observed=time.time()
        with sqlite3.connect(path,timeout=15) as db:
            db.execute('UPDATE media_jobs SET rows=?,created=? WHERE key=?',(json.dumps(rows),observed,key))
    return rows[:limit],observed


def account_rows(project):
    from live_discovery import cache_key
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS competitor_accounts(
            project_key TEXT, competitor TEXT, platform TEXT, handle TEXT, verified_by TEXT, checked_at REAL,
            PRIMARY KEY(project_key,competitor,platform))''')
        return db.execute('SELECT competitor,platform,handle,verified_by FROM competitor_accounts WHERE project_key=?',
                          (cache_key(project),)).fetchall()


def publishers(project):
    return {(platform,handle):name for name,platform,handle,_ in account_rows(project) if handle}


def definitions(project):
    groups={}
    for raw in getattr(project,'competitors',[]) or []:
        entries=[value.strip() for value in raw.split(',') if value.strip()]
        current=None
        for entry in entries:
            if '://' not in entry:
                current=entry
                groups.setdefault(current,{'profiles':{},'domain':None})
                continue
            found=profile(entry)
            if found:
                platform,handle=found
                groups.setdefault(current or handle,{'profiles':{},'domain':None})['profiles'][platform]=handle
            elif current:
                url=urlsplit(entry)
                if url.scheme=='https' and url.hostname and not url.username and not url.password:
                    groups[current]['domain']=url.hostname.removeprefix('www.')
    return groups


def collect_for_project(project,*,suggestions=()):
    from datetime import datetime,timezone
    from live_discovery import cache_key
    from native_conversations import normalize
    from research_providers import sources_from_media_rows,remember_public_sources,MediaPending
    from native_access import NativeCapacityUnavailable
    from provider_budget import BudgetExceeded
    given=definitions(project)
    cached={(name,platform):(handle,basis) for name,platform,handle,basis in account_rows(project)}
    inferred={name:{'profiles':{},'domain':None} for name in suggestions[:3] if name not in given}
    targets={**inferred,**given,**{name:given.get(name,inferred.get(name,{'profiles':{},'domain':None})) for name,_ in cached}}
    output=[]
    report={'competitors_given':list(given),'competitors_discovered':list(inferred),'accounts_verified':[],'posts_collected':0,'posts_accepted':0}
    if os.environ.get('OUTLOUD_MEDIA_SEARCH_ALLOWED')!='1' or os.environ.get('OUTLOUD_MEDIA_START_ALLOWED')!='1':
        return output,report
    for name,definition in targets.items():
        if suggestions and name not in inferred:continue
        for platform in PLATFORMS:
            if name not in given and name not in inferred and (name,platform) not in cached:continue
            if platform=='TikTok' and os.environ.get('OUTLOUD_TIKTOK_EVALUATION_APPROVED')!='1':continue
            try:
                if (name,platform) in cached:
                    handle,basis=cached[name,platform]
                else:
                    handle=definition['profiles'].get(platform)
                    basis='supplied_profile'
                    if not handle:
                        rows,_=collect(platform,name,False)
                        matches={h for row in rows if isinstance(row,dict) and (h:=official_handle(row,name,definition['domain']))}
                        handle=next(iter(matches)) if len(matches)==1 else None
                        basis='native_profile_and_product_link' if handle else 'unverified'
                    with connect() as db:
                        db.execute('INSERT OR REPLACE INTO competitor_accounts VALUES(?,?,?,?,?,?)',
                                   (cache_key(project),name,platform,handle,basis,time.time()))
                if not handle:continue
                report['accounts_verified'].append({'competitor':name,'platform':platform,'handle':handle,'verified_by':basis})
                rows,observed=collect(platform,handle,True)
                sources=normalize(rows,platform) if platform=='X' else sources_from_media_rows(rows,platform)
                sources=[source for source in sources if source_handle(source)==handle]
                for source in sources:
                    source['metrics']['checked_at']=datetime.fromtimestamp(observed,timezone.utc).isoformat()
                output.extend(sources)
            except (BudgetExceeded,NativeCapacityUnavailable):
                report['posts_collected']=len(output)
                remember_public_sources(output)
                return output,report
            except (httpx.HTTPError,RuntimeError,ValueError,MediaPending) as error:
                report.setdefault('unavailable',[]).append({'competitor':name,'platform':platform,'reason':type(error).__name__})
    report['posts_collected']=len(output)
    remember_public_sources(output)
    return output,report
