"""Forward Stripe sandbox webhooks without putting keys in process arguments/logs."""
import json,os,re,subprocess
from pathlib import Path
p=Path('.dev.vars')
values={k:json.loads(v) for k,v in (line.split('=',1) for line in p.read_text().splitlines() if '=' in line)}
env=dict(os.environ);env['STRIPE_API_KEY']=values['STRIPE_SECRET_KEY']
proc=subprocess.Popen(['stripe','listen','--forward-to','http://127.0.0.1:8788/webhooks/stripe','--events','checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,charge.refunded,charge.dispute.created'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
try:
 for line in proc.stdout:
  match=re.search(r'whsec_[a-zA-Z0-9]+',line)
  if match:
   values['STRIPE_WEBHOOK_SECRET']=match.group();p.write_text(''.join(k+'='+json.dumps(v)+'\n' for k,v in values.items()));os.chmod(p,0o600)
   print('Sandbox webhook listener ready; signing secret saved locally (hidden).',flush=True)
  elif '-->' in line or '<--' in line:
   print(re.sub(r'whsec_\w+','[redacted]',line).strip(),flush=True)
finally:
 proc.terminate()
