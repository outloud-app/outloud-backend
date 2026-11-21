#!/usr/bin/env python3
"""Run the local verified-results service without paid provider execution."""
import os
import shlex
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
env=dict(os.environ)
config=Path.home()/'.config/outloud/research.env'
if config.exists():
    for line in config.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,separator,value=line.removeprefix('export ').partition('=')
        if separator:
            parsed=shlex.split(value,comments=True)
            env[key.strip()]=parsed[0] if parsed else ''
env.update(OUTLOUD_LIVE_SEARCH='1',OUTLOUD_LOCAL_TESTING='1',OUTLOUD_LOCAL_DESKTOP='1',
           OUTLOUD_PAID_RESEARCH='1',OUTLOUD_RETRIEVAL_MODE='native',
           OUTLOUD_RESEARCH_CACHE_ONLY='1',OUTLOUD_CONVERSATION_START_ALLOWED='0',
           OUTLOUD_MEDIA_START_ALLOWED='0',OUTLOUD_MEDIA_SEARCH_ALLOWED='0')
# The local app may opt into native testing; web-index retrieval stays off.
if env.get('OUTLOUD_LOCAL_LIVE_NATIVE')=='1':
    env.update(OUTLOUD_RESEARCH_CACHE_ONLY='0',OUTLOUD_MEDIA_START_ALLOWED='1',
               OUTLOUD_MEDIA_SEARCH_ALLOWED='1',OUTLOUD_CONVERSATION_START_ALLOWED='1',
               OUTLOUD_TIKTOK_EVALUATION_APPROVED='1')
os.chdir(ROOT/'research')
os.execve(sys.executable,[sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port','8766'],env)
