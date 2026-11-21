"""Run the local bounded native-platform collector with the existing private configuration."""
import os,sys,runpy
from pathlib import Path
root=Path(__file__).resolve().parents[2]
for line in (Path.home()/'.config/outloud/research.env').read_text().splitlines():
 if line.strip() and not line.startswith('#') and '=' in line:
  key,value=line.split('=',1);os.environ[key]=value.strip().strip('"').strip("'")
# Live execution remains explicitly opt-in and lifetime-budget limited.
if os.environ.get('OUTLOUD_LOCAL_LIVE_NATIVE')=='1':
 os.environ.update(OUTLOUD_PAID_RESEARCH='1',OUTLOUD_MEDIA_START_ALLOWED='1',OUTLOUD_MEDIA_SEARCH_ALLOWED='1',OUTLOUD_CONVERSATION_START_ALLOWED='1',OUTLOUD_TIKTOK_EVALUATION_APPROVED='1')
else:
 os.environ.update(OUTLOUD_MEDIA_START_ALLOWED='0',OUTLOUD_MEDIA_SEARCH_ALLOWED='0',OUTLOUD_CONVERSATION_START_ALLOWED='0')
sys.path.insert(0,str(root/'research'))
runpy.run_path(str(root/'research/collect_public.py'),run_name='__main__')
