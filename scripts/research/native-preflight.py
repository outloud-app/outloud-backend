"""Read-only native acquisition preflight. No provider calls, tokens or new jobs."""
import json
import os
import sqlite3
import sys
import shlex
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
config=Path.home()/'.config/outloud/research.env'
if config.exists():
    for line in config.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        name,separator,value=line.removeprefix('export ').partition('=')
        if separator:
            parts=shlex.split(value,comments=True);os.environ[name.strip()]=parts[0] if parts else ''
sys.path.insert(0,str(ROOT/'research'))
from research_routing import mode
from native_conversations import collector
from provider_budget import APPROVED_CEILING_MICROUSD

budget=Path(os.environ.get('OUTLOUD_BUDGET_DB',str(ROOT/'research/.data/provider-budget.sqlite3')))
reserved=0
if budget.exists():
    with sqlite3.connect('file:'+str(budget)+'?mode=ro',uri=True) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='provider_spend'").fetchone():
            reserved=db.execute('SELECT COALESCE(SUM(reserved),0) FROM provider_spend').fetchone()[0]
ceiling=min(int(os.environ.get('OUTLOUD_EVALUATION_BUDGET_MICROUSD','5000000')),APPROVED_CEILING_MICROUSD)
report={
    'mode':mode(),
    'credentials_present':{name:bool(os.environ.get(name)) for name in ('APIFY_TOKEN','GEMINI_API_KEY')},
    'gates':{name:os.environ.get(name)=='1' for name in (
        'OUTLOUD_PAID_RESEARCH','OUTLOUD_MEDIA_SEARCH_ALLOWED','OUTLOUD_MEDIA_START_ALLOWED',
        'OUTLOUD_TIKTOK_EVALUATION_APPROVED','OUTLOUD_CONVERSATION_START_ALLOWED')},
    'collection_plan':[
        {'platform':platform,'lane':lane,'maximum_posts':20,'maximum_run_usd':cap}
        for lane in ('discover','competitors')
        for platform,cap in (('TikTok',.50),('Instagram',.10))
    ]+[
        {'platform':platform,'lane':'conversations','query_group':group,'maximum_posts':20,'maximum_run_usd':collector(platform)[2]}
        for platform in ('Reddit','X')
        for group in ('customer_task','workflow_friction','adjacent_activity')
    ],
    'budget':{'ceiling_usd':ceiling/1_000_000,'reserved_usd':reserved/1_000_000,
              'unreserved_usd':max(0,ceiling-reserved)/1_000_000},
    'note':'Collection caps exclude planning, evaluation and any subsequent media refresh. This command cannot enable or start research.',
    'provider_calls':0,
}
if '--verify-access' in sys.argv:
    from native_access import require,NativeAccessUnavailable
    try:require();report['native_access']='verified'
    except NativeAccessUnavailable:report['native_access']='unavailable'
    report['note']='Credential preflight may read collector metadata; it never starts an actor or reserves paid collection work.'
print(json.dumps(report,indent=2))
