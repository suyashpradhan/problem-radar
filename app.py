#!/usr/bin/env python3
"""Problem Radar: zero-dependency, local-first public-source research MVP."""
import html, json, os, re, sqlite3, threading, time, urllib.error, urllib.parse, urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = Path(os.getenv('RADAR_DB', str(BASE / 'radar.db')))
PORT = int(os.getenv('PORT', '8765'))
LOCK = threading.RLock()
TOPICS = {
 'stripe-reconciliation': {'label':'Stripe payout reconciliation','query':['stripe payout reconcile','stripe fees refund accounting','stripe payout invoice mismatch'],'terms':['stripe','payout','reconcil','refund','transaction','invoice','accounting','fee','bank','chargeback'],'description':'Matching Stripe transactions, payouts, refunds, fees and invoices with books and bank deposits.'},
 'client-onboarding': {'label':'Client onboarding handoffs','query':['client onboarding spreadsheet','customer onboarding manual tracking','implementation onboarding checklist'],'terms':['onboarding','handoff','checklist','implementation','client','customer','spreadsheet','setup'],'description':'Tracking owners, missing steps and delays in customer/client onboarding.'},
 'invoice-followup': {'label':'Overdue invoice follow-ups','query':['overdue invoice follow up','chasing client payments','invoice payment reminders manual'],'terms':['invoice','payment','overdue','chasing','reminder','client','follow up','paid'],'description':'Chasing unpaid invoices and tracking outstanding balances.'},
 'document-collection': {'label':'Chasing client documents','query':['collecting documents from clients','missing documents client accountant','document request checklist'],'terms':['document','missing','upload','client','request','accountant','tax','collect'],'description':'Following up on missing documents and approvals.'},
 'saas-renewals': {'label':'SaaS subscription renewals','query':['saas subscriptions renewal spreadsheet','software renewals tracking manually','forgot subscription renewal'],'terms':['renewal','subscription','saas','license','tracking','spend','forgot'],'description':'Keeping track of software renewals, owners and unused subscriptions.'},
}
PAIN = re.compile(r'\b(manual(?:ly)?|pain|annoy(?:ing|ed)?|frustrat\w*|wish|hard|difficult|spreadsheet|csv|hours|tedious|reconcil\w*|workaround|broken|problem|missing|struggl\w*|overdue|expensive|not support|doesn.t work|hate|need a tool|looking for|anyone know)\b',re.I)

def now(): return datetime.now(timezone.utc).isoformat()
@contextmanager
def conn():
 c=sqlite3.connect(DB, timeout=20)
 try:
  c.row_factory=sqlite3.Row
  c.execute('PRAGMA journal_mode=WAL')
  with c: yield c
 finally: c.close()

def init():
 with conn() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS evidence(id TEXT NOT NULL,topic TEXT NOT NULL,source TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,url TEXT NOT NULL,published TEXT,author TEXT,score INTEGER DEFAULT 0,found_at TEXT NOT NULL, PRIMARY KEY(id,topic), UNIQUE(url,topic));
 CREATE TABLE IF NOT EXISTS competitors(id INTEGER PRIMARY KEY AUTOINCREMENT,topic TEXT NOT NULL,name TEXT NOT NULL,url TEXT NOT NULL,pricing TEXT DEFAULT '',pricing_url TEXT DEFAULT '',kind TEXT NOT NULL DEFAULT 'paid',complaint TEXT DEFAULT '',complaint_url TEXT DEFAULT '',verified_on TEXT DEFAULT '',created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS decisions(topic TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'Discovery',notes TEXT DEFAULT '',updated_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT NOT NULL,ended_at TEXT,status TEXT NOT NULL,found INTEGER DEFAULT 0,added INTEGER DEFAULT 0,errors TEXT DEFAULT '');
 CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
  # Preserve existing data while allowing one source item in multiple topics.
  pk=[r['name'] for r in c.execute('PRAGMA table_info(evidence)') if r['pk']]
  if pk == ['id']:
   c.executescript("""BEGIN IMMEDIATE;
    ALTER TABLE evidence RENAME TO evidence_old;
    CREATE TABLE evidence(id TEXT NOT NULL,topic TEXT NOT NULL,source TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,url TEXT NOT NULL,published TEXT,author TEXT,score INTEGER DEFAULT 0,found_at TEXT NOT NULL,PRIMARY KEY(id,topic),UNIQUE(url,topic));
    INSERT INTO evidence SELECT * FROM evidence_old;
    DROP TABLE evidence_old;
    COMMIT;""")
  c.executescript("""CREATE TABLE IF NOT EXISTS source_health(source TEXT PRIMARY KEY,next_allowed REAL NOT NULL DEFAULT 0,status TEXT,last_attempt TEXT,last_error TEXT);
   CREATE TABLE IF NOT EXISTS collection_requests(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL,source TEXT NOT NULL,topic TEXT NOT NULL,query TEXT NOT NULL,status TEXT NOT NULL,found INTEGER DEFAULT 0,added INTEGER DEFAULT 0,error TEXT DEFAULT '',attempted_at TEXT NOT NULL);""")
  for slug in TOPICS: c.execute('INSERT OR IGNORE INTO decisions(topic,status,updated_at) VALUES(?,?,?)',(slug,'Discovery',now()))

def request_json(url,headers=None):
 h={'User-Agent':'ProblemRadarResearch/0.1 (local personal research; respectful rate limits)','Accept':'application/json'}
 if headers: h.update(headers)
 with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=12) as resp:
  return json.load(resp)

def strip(raw): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',raw or ''))).strip()[:5000]

def find_hn(topic,term):
 args=urllib.parse.urlencode({'query':term,'hitsPerPage':25,'numericFilters':f'created_at_i>{int((datetime.now(timezone.utc)-timedelta(days=730)).timestamp())}'})
 data=request_json('https://hn.algolia.com/api/v1/search_by_date?'+args)
 if not isinstance(data,dict) or not isinstance(data.get('hits'),list): raise ValueError('Invalid HN response: missing hits array')
 for x in data['hits']:
  oid=str(x.get('objectID') or '')
  if not oid: continue
  body=strip(x.get('comment_text') or x.get('story_text') or '')
  title=strip(x.get('title') or x.get('story_title') or '') or body[:120] or 'Hacker News discussion'
  yield dict(id='hn:'+oid,source='Hacker News',topic=topic,title=title,body=body,url='https://news.ycombinator.com/item?id='+oid,published=x.get('created_at'),author=x.get('author'),score=x.get('points') or 0)

def find_github(topic,term):
 query=urllib.parse.urlencode({'q':term+' in:title,body is:issue','sort':'updated','order':'desc','per_page':15})
 token=os.getenv('GITHUB_TOKEN','')
 data=request_json('https://api.github.com/search/issues?'+query, {'Authorization':'Bearer '+token} if token else {})
 if not isinstance(data,dict) or not isinstance(data.get('items'),list): raise ValueError('Invalid GitHub response: missing items array')
 if data.get('incomplete_results'): raise ValueError('GitHub returned incomplete search results; narrow the query')
 for x in data['items']:
  yield dict(id='gh:'+str(x['id']),source='GitHub',topic=topic,title=strip(x.get('title')),body=strip(x.get('body')),url=x.get('html_url'),published=x.get('created_at'),author=(x.get('user') or {}).get('login'),score=x.get('comments') or 0)

class ScanBusy(Exception): pass

# Below unauthenticated GitHub search limits; bounded jobs, no paid API calls.
SOURCE_INTERVALS = {'hn': 1.0, 'github': 7.0}
MAX_REQUESTS = 30

def scan(topics=None,source='all',queries_per_topic=2):
 topics=list(TOPICS) if topics is None else list(dict.fromkeys(topics))
 if not topics or any(t not in TOPICS for t in topics): raise ValueError('Unknown or empty topics')
 if source not in ('all','hn','github'): raise ValueError('Invalid source')
 if type(queries_per_topic) is not int or not 1 <= queries_per_topic <= 3: raise ValueError('Queries must be between 1 and 3')
 # SQLite lease protects manual and scheduled scans across processes.
 with conn() as c:
  c.execute('BEGIN IMMEDIATE')
  cutoff=(datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat()
  c.execute("UPDATE runs SET status='interrupted',ended_at=?,errors='Scan lease expired; process may have stopped' WHERE status='running' AND started_at<?",(now(),cutoff))
  if c.execute("SELECT 1 FROM runs WHERE status='running'").fetchone(): raise ScanBusy('A scan is already running; retry after it finishes (stale leases expire after 30 minutes)')
  rid=c.execute('INSERT INTO runs(started_at,status) VALUES(?,?)',(now(),'running')).lastrowid
 total=0; added=0; errors=[]; succeeded=0; attempted=0
 try:
  for topic in topics:
   for term in TOPICS[topic]['query'][:queries_per_topic]:
    for src,func in [('hn',find_hn),('github',find_github)]:
     if source not in ('all',src): continue
     count=0; inserted=0; error=''; status='complete'
     with conn() as c: health=c.execute('SELECT * FROM source_health WHERE source=?',(src,)).fetchone()
     wait=max(0,health['next_allowed']-time.time()) if health else 0
     if attempted >= MAX_REQUESTS or wait > SOURCE_INTERVALS[src]+1:
      status='skipped'; error='Request budget exhausted' if attempted >= MAX_REQUESTS else 'Source cooldown active; retry later'
     else:
      time.sleep(wait); attempted+=1
      cooldown=SOURCE_INTERVALS[src]
      try:
       items=list(func(topic,term)); count=len(items); total+=count
       with conn() as c:
        for x in items:
         if not valid_url(x.get('url')) or not x.get('published'): raise ValueError('Source item lacks a valid URL or publication date')
         before=c.total_changes
         c.execute('INSERT OR IGNORE INTO evidence(id,topic,source,title,body,url,published,author,score,found_at) VALUES(?,?,?,?,?,?,?,?,?,?)',tuple(x[k] for k in ('id','topic','source','title','body','url','published','author','score'))+(now(),))
         inserted+=c.total_changes-before
       added+=inserted; succeeded+=1
      except Exception as exc:
       inserted=0; status='failed'
       error=f'{type(exc).__name__}: {exc}'
       if isinstance(exc,urllib.error.HTTPError) and exc.code in (403,429):
        status='rate_limited'; cooldown=60
        try: cooldown=max(cooldown,float(exc.headers.get('Retry-After','0')),float(exc.headers.get('X-RateLimit-Reset','0'))-time.time())
        except (ValueError,TypeError): pass
      with conn() as c:
       c.execute('INSERT OR REPLACE INTO source_health(source,next_allowed,status,last_attempt,last_error) VALUES(?,?,?,?,?)',(src,time.time()+cooldown,status,now(),error))
     if error: errors.append(f'{src}/{topic}/{term}: {error}')
     with conn() as c:
      c.execute('INSERT INTO collection_requests(run_id,source,topic,query,status,found,added,error,attempted_at) VALUES(?,?,?,?,?,?,?,?,?)',(rid,src,topic,term,status,count,inserted,error,now()))
  status='complete' if not errors else 'partial' if succeeded else 'failed'
 except BaseException:
  with conn() as c: c.execute("UPDATE runs SET ended_at=?,status='interrupted',found=?,added=?,errors=? WHERE id=?",(now(),total,added,'Unexpected interruption; inspect server logs',rid))
  raise
 with conn() as c:c.execute('UPDATE runs SET ended_at=?,status=?,found=?,added=?,errors=? WHERE id=?',(now(),status,total,added,'\n'.join(errors)[:5000],rid))
 return {'run_id':rid,'status':status,'found':total,'added':added,'errors':errors}

def valid_url(value):
 try:
  parsed=urllib.parse.urlparse(value or '')
  return parsed.scheme in ('http','https') and bool(parsed.hostname) and not parsed.username
 except (ValueError,TypeError): return False

def evidence_score(x):
 body=((x['title'] or '')+' '+(x['body'] or '')).lower()
 signals=len(set(m.group(0).lower() for m in PAIN.finditer(body)))
 return min(100, min(6,signals)*12+ min(20,int(x['score'] or 0)))

def overview():
 with conn() as c:
  rows=c.execute('SELECT * FROM evidence').fetchall()
  comps=c.execute('SELECT * FROM competitors').fetchall()
  dec={r['topic']:dict(r) for r in c.execute('SELECT * FROM decisions')}
  runs=[dict(r) for r in c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 8')]
  health=[dict(r) for r in c.execute('SELECT * FROM source_health')]
  for run in runs: run['requests']=[dict(r) for r in c.execute('SELECT * FROM collection_requests WHERE run_id=? ORDER BY id',(run['id'],))]
 groups=[]
 for slug,t in TOPICS.items():
  items=[r for r in rows if r['topic']==slug]
  distinct=len({r['author']+'@'+r['source'] if r['author'] else r['id'] for r in items})
  pain=sum(bool(PAIN.search((r['title'] or '')+' '+(r['body'] or ''))) for r in items)
  paid=sum(1 for r in comps if r['topic']==slug and r['kind']=='paid' and r['pricing_url'])
  free=sum(1 for r in comps if r['topic']==slug and r['kind']=='free')
  complaints=sum(1 for r in comps if r['topic']==slug and r['complaint_url'])
  # A conservative evidence gate. Status never automatically becomes 'build'.
  gate='Needs more independent complaints' if pain<5 or distinct<5 else 'Research competitor pricing' if paid<3 else 'Research free alternatives' if not free else 'Research customer complaints' if complaints<2 else 'Customer interviews required'
  groups.append({'slug':slug,'label':t['label'],'description':t['description'],'sources':len(items),'unique_authors':distinct,'pain_signals':pain,'paid_priced':paid,'free_alternatives':free,'competitor_complaints':complaints,'gate':gate,'status':dec[slug]['status'],'notes':dec[slug]['notes']})
 return {'topics':groups,'runs':runs,'source_health':health,'total_evidence':len(rows),'source_counts':dict((s,sum(r['source']==s for r in rows)) for s in ['Hacker News','GitHub'])}

def evidence(topic,search='',limit=100):
 with conn() as c: rows=c.execute('SELECT * FROM evidence WHERE topic=? ORDER BY published DESC LIMIT 600',(topic,)).fetchall()
 result=[]
 for r in rows:
  if search and search.lower() not in (r['title']+' '+r['body']).lower(): continue
  z=dict(r);z['pain_score']=evidence_score(r);z['has_pain_signal']=bool(PAIN.search(r['title']+' '+r['body']));result.append(z)
 return sorted(result,key=lambda r:(r['has_pain_signal'],r['pain_score'],r['published'] or ''),reverse=True)[:limit]

def competitors(topic):
 with conn() as c: return [dict(r) for r in c.execute('SELECT * FROM competitors WHERE topic=? ORDER BY id DESC',(topic,))]

def seed():
 # Pricing examples are only preloaded when sourced and labeled as externally verified reference pages.
 with conn() as c:
  if c.execute('SELECT count(*) FROM competitors').fetchone()[0]: return
  for name,url,price,purl,kind in [
   ('Synder','https://synder.com/','From $65/month (monthly billed); $52/month annual billing, Basic','https://synder.com/pricing/','paid'),
   ('Stripe Dashboard / exports','https://dashboard.stripe.com/','Included Stripe reporting and exports; platform processing fees still apply','https://docs.stripe.com/reports','free')]:
   c.execute('INSERT INTO competitors(topic,name,url,pricing,pricing_url,kind,verified_on,created_at) VALUES(?,?,?,?,?,?,?,?)',('stripe-reconciliation',name,url,price,purl,kind,'2026-10-31',now()))

class Handler(BaseHTTPRequestHandler):
 def log_message(self,fmt,*args): print('%s %s'%(self.address_string(),fmt%args))
 def send(self,data,status=200):
  body=json.dumps(data,ensure_ascii=False,default=str).encode()
  self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
 def read_body(self):
  try: n=int(self.headers.get('Content-Length','0'))
  except ValueError:self.send({'error':'Invalid Content-Length'},400);return None
  if n<0:self.send({'error':'Invalid Content-Length'},400);return None
  if n>100000:self.send({'error':'Payload too large'},413);return None
  try:
   data=json.loads(self.rfile.read(n) or b'{}')
   if not isinstance(data,dict): raise ValueError('Expected object')
   return data
  except Exception:self.send({'error':'Invalid JSON'},400);return None
 def do_GET(self):
  path=urllib.parse.urlparse(self.path);q=urllib.parse.parse_qs(path.query)
  if path.path=='/api/overview':return self.send(overview())
  if path.path=='/api/evidence':return self.send(evidence(q.get('topic',['stripe-reconciliation'])[0],q.get('q',[''])[0]))
  if path.path=='/api/competitors':return self.send(competitors(q.get('topic',['stripe-reconciliation'])[0]))
  if path.path=='/api/health':return self.send({'ok':True,'db':str(DB),'time':now()})
  rel=path.path.lstrip('/') or 'index.html'
  if rel not in ('index.html','app.js','style.css'):return self.send({'error':'not found'},404)
  f=BASE/'static'/rel
  if not f.exists():return self.send({'error':'not found'},404)
  blob=f.read_bytes();self.send_response(200);self.send_header('Content-Type',{'index.html':'text/html; charset=utf-8','app.js':'text/javascript','style.css':'text/css'}[rel]);self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob)
 def do_POST(self):
  data=self.read_body()
  if data is None:return
  if self.path=='/api/scan':
   topic=data.get('topic') or None
   if topic and (not isinstance(topic,str) or topic not in TOPICS):return self.send({'error':'Unknown topic'},400)
   source=data.get('source','all')
   if source not in ('all','hn','github'):return self.send({'error':'Invalid source'},400)
   try:return self.send(scan([topic] if topic else None,source,1 if not topic else 3))
   except ScanBusy as exc:return self.send({'error':str(exc)},409)
  if self.path=='/api/competitors':
   topic=data.get('topic');kind=data.get('kind','paid')
   if topic not in TOPICS or kind not in ('paid','free') or not data.get('name') or not data.get('url'):return self.send({'error':'Topic, name, URL, kind required'},400)
   for key in ('url','pricing_url','complaint_url'):
    if data.get(key) and urllib.parse.urlparse(data[key]).scheme not in ('http','https'):return self.send({'error':f'Invalid {key}'},400)
   with conn() as c:
    c.execute('INSERT INTO competitors(topic,name,url,pricing,pricing_url,kind,complaint,complaint_url,verified_on,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(topic,data['name'][:120],data['url'],data.get('pricing','')[:400],data.get('pricing_url',''),kind,data.get('complaint','')[:1000],data.get('complaint_url',''),data.get('verified_on',''),now()))
   return self.send({'ok':True})
  if self.path=='/api/decision':
   topic=data.get('topic');status=data.get('status')
   if topic not in TOPICS or status not in ('Discovery','Needs research','Customer validation','Rejected'):return self.send({'error':'Invalid topic or status'},400)
   with conn() as c:c.execute('UPDATE decisions SET status=?,notes=?,updated_at=? WHERE topic=?',(status,str(data.get('notes',''))[:2000],now(),topic))
   return self.send({'ok':True})
  self.send({'error':'not found'},404)

if __name__=='__main__':
 init();seed()
 print(f'Problem Radar ready: http://localhost:{PORT}  |  DB {DB}',flush=True)
 ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
