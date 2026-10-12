"""Run after browser workflow and Compose restart; uses only the stdlib."""
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get('E2E_BASE_URL', 'http://localhost:8080') + '/api/v1'
for attempt in range(60):
    try:
        with urllib.request.urlopen(BASE + '/health/ready', timeout=3) as response:
            if response.status == 200: break
    except (urllib.error.URLError, TimeoutError): time.sleep(1)
else: raise SystemExit('Services did not become ready after restart')

def client(role):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    body = json.dumps({'email':role+'@example.test','password':os.environ['DEMO_'+role.upper()+'_PASSWORD']}).encode()
    opener.open(urllib.request.Request(BASE+'/auth/login',data=body,headers={'Content-Type':'application/json'}))
    return opener

student, admin = client('student'), client('admin')
def get(opener, path): return json.load(opener.open(BASE+path,timeout=5))
tickets=get(student,'/tickets')['items']
ticket=next(t for t in tickets if t['title']=='E2E VPN 809 服务请求')
assert ticket['status']=='closed'
assert get(student,'/tickets/'+ticket['id'])['replies']
doc=next(d for d in get(admin,'/documents')['items'] if d['name']=='e2e-vpn.md')
assert doc['active_version_id']
with admin.open(BASE+'/documents/'+doc['id']+'/download') as response: assert b'VPN' in response.read()
assert get(student,'/conversations')['total'] > 0
print('Persistence verified: users, published document/file, conversation, closed ticket and replies')
