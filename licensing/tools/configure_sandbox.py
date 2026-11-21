"""Read credentials via hidden stdin, validate test mode, write ignored local secrets.
Never accepts secrets as command-line arguments or prints them.
"""
import json,os,secrets,sys,urllib.request,urllib.error
from pathlib import Path
import getpass
key=getpass.getpass("Sandbox secret key (input hidden): ")
if not key.startswith(('sk_test_','rk_test_')): raise SystemExit('A sandbox/test key is required.')
request=urllib.request.Request('https://api.stripe.com/v1/balance',headers={'Authorization':'Bearer '+key,'Stripe-Version':'2026-09-30.endive'})
try:
 with urllib.request.urlopen(request,timeout=20) as r: result=json.load(r)
except urllib.error.HTTPError as e: raise SystemExit('Stripe authentication failed: HTTP '+str(e.code))
if result.get('livemode') is not False: raise SystemExit('Refusing a live-mode connection.')
path=Path('.dev.vars')
previous={}
if path.exists():
 for line in path.read_text().splitlines():
  if '=' in line:
   k,v=line.split('=',1)
   try: previous[k]=json.loads(v)
   except ValueError: pass
previous.update(STRIPE_SECRET_KEY=key,LICENSE_ISSUER_V1=previous.get('LICENSE_ISSUER_V1') or secrets.token_urlsafe(48),GATEWAY_SECRET=previous.get('GATEWAY_SECRET') or secrets.token_urlsafe(32),ADMIN_SECRET=previous.get('ADMIN_SECRET') or secrets.token_urlsafe(32))
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:
 for k,v in previous.items(): f.write(k+'='+json.dumps(v)+'\n')
print('Stripe sandbox authenticated. Local test secrets stored in ignored mode-600 configuration. No live credentials used.')
