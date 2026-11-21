"""Provision a signed Stripe TEST webhook and upload secrets via stdin.
No credential values are printed or passed as process arguments.
"""
import json,os,subprocess,sys,urllib.request
from pathlib import Path
from urllib.parse import urlencode,urlsplit

root=Path(__file__).resolve().parents[1]
site=Path('/Users/apple/VSCodeProjects/outloud-website')
node='/Users/apple/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
wrangler=str(site/'node_modules/wrangler/bin/wrangler.js')
url=sys.argv[1].rstrip('/')
u=urlsplit(url)
if u.scheme!='https' or not u.hostname.startswith('outloud-license-sandbox.') or not u.hostname.endswith('.workers.dev'):
 raise SystemExit('Expected the deployed Outloud sandbox Worker URL.')
local={k:json.loads(v) for k,v in (line.split('=',1) for line in (root/'.dev.vars').read_text().splitlines() if '=' in line)}
if not local['STRIPE_SECRET_KEY'].startswith(('sk_test_','rk_test_')): raise SystemExit('Refusing a live key.')
p=root/'.dev.vars.remote'
if p.exists():
 values={k:json.loads(v) for k,v in (line.split('=',1) for line in p.read_text().splitlines() if '=' in line)}
else:
 values={k:local[k] for k in ['STRIPE_SECRET_KEY','LICENSE_ISSUER_V1','GATEWAY_SECRET','ADMIN_SECRET']}
 payload={'url':url+'/webhooks/stripe','api_version':'2026-09-30.endive','description':'Outloud hosted license sandbox','enabled_events[]':['checkout.session.completed','checkout.session.async_payment_succeeded','checkout.session.async_payment_failed','charge.refunded','charge.dispute.created']}
 request=urllib.request.Request('https://api.stripe.com/v1/webhook_endpoints',data=urlencode(payload,doseq=True).encode(),headers={'Authorization':'Bearer '+values['STRIPE_SECRET_KEY'],'Stripe-Version':'2026-09-30.endive','Idempotency-Key':'outloud-hosted-sandbox-webhook-v1'})
 with urllib.request.urlopen(request,timeout=25) as response: endpoint=json.load(response)
 if endpoint.get('livemode') is not False or not endpoint.get('secret'):raise SystemExit('Invalid sandbox endpoint response.')
 values['STRIPE_WEBHOOK_SECRET']=endpoint['secret']
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as f:
  for k,v in values.items():f.write(k+'='+json.dumps(v)+'\n')
 (root/'hosted-sandbox.json').write_text(json.dumps({'url':url,'webhook_id':endpoint['id'],'livemode':False},indent=2)+'\n')
print('Stripe sandbox webhook configured (signing secret hidden).',flush=True)
settings=dict(os.environ);settings['CLOUDFLARE_ACCOUNT_ID']='535b814e25e0ef791e219878f2d1825c'
for command,payload,cwd in [
 ([node,wrangler,'secret','bulk'],values,root),
 ([node,wrangler,'pages','secret','bulk','--project-name','tryoutloud'],{'LICENSE_GATEWAY_SECRET':values['GATEWAY_SECRET']},site)
]:
 result=subprocess.run(command,input=json.dumps(payload),text=True,capture_output=True,cwd=cwd,env=settings)
 if result.returncode:
  print('Secret upload failed for '+('Worker' if cwd==root else 'Pages')+'; no secret values displayed.')
  raise SystemExit(result.returncode)
 print(('Worker' if cwd==root else 'Pages')+' secrets saved in Cloudflare.',flush=True)
