"""Validate native-collector credentials before reserving paid collection work."""
import hashlib,os,sqlite3,time
from pathlib import Path
import httpx

class NativeAccessUnavailable(RuntimeError):pass


class NativeCapacityUnavailable(NativeAccessUnavailable):pass


CAPACITY_MESSAGE='Apify has reached its monthly account allowance. Saved results are still available.'


def actor_start(post, url, **kwargs):
    """Retry explicit concurrency rejections without reserving or starting a second job."""
    delays=(2, 4, 8, 16, 0)
    for delay in delays:
        response=post(url,**kwargs)
        if not delay or response.status_code!=402:
            break
        try:
            error_type=(response.json().get('error') or {}).get('type')
        except (AttributeError, ValueError):
            break
        if error_type!='concurrent-runs-limit-exceeded':
            break
        time.sleep(delay)
    raise_for_actor_start(response)
    return response.json()['data']


def raise_for_actor_start(response):
    """A provider-wide cap applies across actors, so stop reserving at each adapter."""
    if response.status_code==403:
        try:error=response.json().get('error') or {}
        except ValueError:error={}
        if error.get('type')=='platform-feature-disabled' and 'monthly usage' in error.get('message','').lower():
            fingerprint, path=access_record()
            with sqlite3.connect(path,timeout=15) as db:
                db.execute('CREATE TABLE IF NOT EXISTS native_access_state(key TEXT PRIMARY KEY,valid INTEGER,checked REAL)')
                db.execute('INSERT OR REPLACE INTO native_access_state VALUES(?,0,?)',('capacity:'+fingerprint,time.time()))
            raise NativeCapacityUnavailable(CAPACITY_MESSAGE)
    response.raise_for_status()


def access_record():
    token=os.environ.get('APIFY_TOKEN','')
    fingerprint='actor-read-v1:'+hashlib.sha256(token.encode()).hexdigest()
    path=Path(os.environ.get('OUTLOUD_PROVIDER_CACHE',str(Path(__file__).parent/'.data/provider-media.sqlite3')))
    path.parent.mkdir(parents=True,exist_ok=True)
    return fingerprint,path


def check(token,client=None):
    if not token:raise NativeAccessUnavailable('Native platform collection needs a configured provider credential.')
    response=(client or httpx).get('https://api.apify.com/v2/acts/clockworks~tiktok-scraper',
                  headers={'Authorization':'Bearer '+token},timeout=12)
    if response.status_code in (401,403):
        raise NativeAccessUnavailable('Native platform collection is unavailable: the configured provider credential was rejected. Existing saved results are preserved.')
    if response.status_code!=200:
        raise NativeAccessUnavailable('Native platform collection is temporarily unavailable. Existing saved results are preserved.')
    return True


def require():
    import fcntl
    token=os.environ.get('APIFY_TOKEN','')
    if not token:raise NativeAccessUnavailable('Native platform collection needs a configured provider credential.')
    fingerprint,path=access_record()
    locks=path.parent/'.collection-locks';locks.mkdir(exist_ok=True)
    with (locks/('access-'+fingerprint)).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        with sqlite3.connect(path,timeout=15) as db:
            db.execute('CREATE TABLE IF NOT EXISTS native_access_state(key TEXT PRIMARY KEY,valid INTEGER,checked REAL)')
            capacity=db.execute('SELECT checked FROM native_access_state WHERE key=?',('capacity:'+fingerprint,)).fetchone()
            row=db.execute('SELECT valid,checked FROM native_access_state WHERE key=?',(fingerprint,)).fetchone()
        if capacity and time.time()-capacity[0]<900:
            raise NativeCapacityUnavailable(CAPACITY_MESSAGE)
        if row and time.time()-row[1] < (3600 if row[0] else 60):
            if row[0]:return
            raise NativeAccessUnavailable('Native platform collection is unavailable: check the configured provider credential. Existing saved results are preserved.')
        try:check(token)
        except (NativeAccessUnavailable,httpx.HTTPError):
            with sqlite3.connect(path,timeout=15) as db:db.execute('INSERT OR REPLACE INTO native_access_state VALUES(?,0,?)',(fingerprint,time.time()))
            raise NativeAccessUnavailable('Native platform collection is unavailable: check the configured provider credential or connection. Existing saved results are preserved.') from None
        with sqlite3.connect(path,timeout=15) as db:db.execute('INSERT OR REPLACE INTO native_access_state VALUES(?,1,?)',(fingerprint,time.time()))
