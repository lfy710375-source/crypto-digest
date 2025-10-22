# -*- coding: utf-8 -*-
"""
科创研习社 · 币圈资讯自动推送（小时快报）
- 源：Binance 官方 RSS/CMS + 各大 Statuspage + Nitter 镜像 RSS + 媒体RSS
- 中文化：术语替换；分区；置顶关键词；去重
- 推送：PushPlus（在仓库 Secrets 里配置 PUSHPLUS_TOKEN）
"""

import os, re, time, json, datetime, requests, feedparser, urllib.parse

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN","\").strip()
TIMEOUT = 25
UA = {"User-Agent":"Mozilla/5.0 (GitHubActions) CryptoDigest/1.0"}

# ---------- 数据源 ----------
NITTERS = [
  "https://nitter.net","https://nitter.poast.org",
  "https://nitter.tiekoetter.com","https://nitter.domain.glass",
  "https://nitter.lacontrevoie.fr",
]
def nitter_feeds(h): return [f"{u.rstrip('/')}/{h}/rss" for u in NITTERS]

EX_RSS = [
  "https://www.binance.com/zh-CN/support/announcement/rss",
  *nitter_feeds("binance"), *nitter_feeds("OKX"),
  *nitter_feeds("Bybit_Official"), *nitter_feeds("krakenfx"),
  *nitter_feeds("coinbase")
]
MEDIA_RSS = [
  "https://www.coindesk.com/arc/outboundfeeds/rss/",
  "https://cointelegraph.com/rss", "https://decrypt.co/feed",
  *nitter_feeds("WuBlockchain")
]
ECO_RSS = [
  *nitter_feeds("arbitrum"), *nitter_feeds("optimismFND"),
  *nitter_feeds("zksync"), *nitter_feeds("solana"),
  *nitter_feeds("0xPolygon"), *nitter_feeds("avax"),
  *nitter_feeds("AptosLabs"), *nitter_feeds("SuiNetwork"),
  *nitter_feeds("ton_blockchain"), *nitter_feeds("BuildOnBase"),
]
STATUSPAGES = [
  ("Binance","https://status.binance.com"),
  ("OKX","https://status.okx.com"),
  ("Bybit","https://status.bybit.com"),
  ("Coinbase","https://status.coinbase.com"),
  ("Kraken","https://status.kraken.com"),
]

# ---------- 抓取 ----------
def to_x_link(link:str)->str:
  if not link: return link
  if "nitter" in link:
    u=urllib.parse.urlparse(link); p=u.path.strip("/").split("/")
    if len(p)>=3 and p[1]=="status": return "https://x.com/" + "/".join(p[:3])
  if link.startswith("/"): return "https://x.com"+link
  return link

def fetch_rss(url):
  try:
    r=requests.get(url,headers=UA,timeout=TIMEOUT); r.raise_for_status()
    fp=feedparser.parse(r.content); out=[]
    for e in fp.entries[:40]:
      t=(getattr(e,"title","") or "").strip()
      l=to_x_link((getattr(e,"link","") or "").strip())
      s=(getattr(e,"summary","") or getattr(e,"description","") or "").strip()
      pub=(getattr(e,"published","") or getattr(e,"updated","") or "")
      ts=pub.replace("T"," ").replace("Z","").split("+")[0].strip()
      out.append({"source":url,"title":t,"summary":s,"link":l,"ts":ts})
    return out
  except Exception:
    return []

def fetch_binance_cms(rows=40):
  def parse(j):
    items=[]
    arts=(((j or {}).get("data") or {}).get("articles")) or []
    for a in arts[:rows]:
      title=(a.get("title") or "").strip()
      code=a.get("code") or a.get("id") or ""
      ts_ms=a.get("releaseDate") or a.get("createTime") or 0
      link=f"https://www.binance.com/en/support/announcement/{code}" if code else ""
      try: ts=datetime.datetime.fromtimestamp(ts_ms/1000).strftime("%Y-%m-%d %H:%M")
      except: ts=""
      items.append({"source":"binance_cms","title":title,"summary":"","link":link,"ts":ts})
    return items
  urls=[
    f"https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&page=1&rows={rows}",
    f"https://www.binance.com/bapi/composite/v1/public/cms/article/list?type=1&page=1&rows={rows}",
  ]
  for u in urls:
    try:
      r=requests.get(u,headers=UA,timeout=TIMEOUT)
      if r.status_code==200:
        it=parse(r.json())
        if it: return it
    except: pass
  return []

def fetch_statuspage(base,name):
  url=base.rstrip("/")+"/api/v2/summary.json"
  try:
    r=requests.get(url,headers=UA,timeout=TIMEOUT); r.raise_for_status()
    j=r.json()
  except: return []
  out=[]
  incidents=(j.get("incidents") or []) + (j.get("scheduled_maintenances") or [])
  for inc in incidents[:20]:
    title=inc.get("name") or ""
    status=inc.get("status") or ""
    seg=[]
    if status: seg.append("状态："+status)
    ups=inc.get("incident_updates") or []
    if ups:
      body=(ups[0].get("body") or "").strip()
      if body: seg.append((body[:180]+"…") if len(body)>180 else body)
    summary=" | ".join(seg)
    link=inc.get("shortlink") or base
    ts=(inc.get("created_at") or "").replace("T"," ").replace("Z","").split("+")[0].strip()
    out.append({"source":"status_"+name.lower(),"title":"["+name+" 状态] "+title,"summary":summary,"link":link,"ts":ts})
  return out

# ---------- 中文化 & 分区 ----------
GLOSSARY=[(r'\bspot\b','现货'),(r'\bfutures?\b','期货'),(r'\bperpetual(s)?\b','永续'),
          (r'\bmargin\b','杠杆'),(r'\blist(ed|ing|s)?\b','上线'),(r'\blaunch(ing|ed)?\b','上线'),
          (r'\bmaintenance\b','维护'),(r'\bsuspend(ed|s|ing)?\b','暂停'),(r'\bresume(d|s|ing)?\b','恢复'),
          (r'\bdeposit(s)?\b','充值'),(r'\bwithdraw(al|s|ing)?\b','提现'),
          (r'\bstaking\b','质押'),(r'\bairdrop\b','空投'),(r'\btestnet\b','测试网'),
          (r'\bmainnet\b','主网'),(r'\bsnapshot\b','快照'),(r'\bclaim\b','领取')]
def zhify(s:str)->str:
  s=s or ""
  for pat,rep in GLOSSARY: s=re.sub(pat,rep,s,flags=re.IGNORECASE)
  return re.sub(r'\s+',' ',s).strip()

KEYS=["暂停","维护","黑客","漏洞","上线","永续","期货","现货","下架","空投","测试网","主网","快照","领取"]
def score_hi(t):
  sc=0; out=t
  for kw in KEYS:
    if kw in t: sc+=1; out=out.replace(kw,"**"+kw+"**")
  return sc,("【⚠重点】"+out) if sc>0 else out

def classify(it):
  t=(it["title"]+" "+it["summary"]).lower()
  if any(k in t for k in ["listing","上线","launch","maintenance","维护","perpetual","永续","margin","杠杆","spot","现货","期货","futures","delist","下架"]): return "🔥 新币/运营"
  if any(k in t for k in ["airdrop","空投","测试网","testnet","claim","领取","快照","snapshot","quest"]): return "💧 测试网/空投"
  if any(k in t for k in ["whale","巨鲸","大额转账","转入","转出","on-chain","链上","inflow","outflow"]): return "🐳 链上鲸鱼"
  if any(h in (it["source"] or "") for h in ["binance.com","okx.com","bybit.com","kraken.com","coinbase.com","status_","nitter"]): return "📣 交易所更新"
  if any(k in t for k in ["arbitrum","optimism","zksync","solana","polygon","avax","aptos","sui","ton","base","starknet","sei","celestia","near","cosmos"]): return "🌐 生态叙事"
  return "🏦 媒体头条"

SECTIONS=[("🔥 新币/运营","🔥 新币/运营"),("💧 测试网/空投","💧 测试网/空投"),
          ("🐳 链上鲸鱼","🐳 链上鲸鱼"),("📣 交易所更新","📣 交易所更新"),
          ("🏦 媒体头条","🏦 媒体头条"),("🌐 生态叙事","🌐 生态叙事")]

def build_md(buckets, per_sec=10):
  ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
  parts=[f"**本地时间**：{ts}  \n**科创研习社专用**\n"]
  for title,key in SECTIONS:
    arr=buckets.get(key,[])
    if not arr: continue
    lines=[]; seen=set()
    for it in arr:
      if it["link"] and it["link"] in seen: continue
      seen.add(it["link"]); ttl=zhify(it["title"]); sc,ttl=score_hi(ttl)
      ts2=it["ts"] or "N/A"
      lines.append(f"- {ttl}\n  ⏱ {ts2}  |  🔗 [原文]({it['link']})")
      if len(lines)>=per_sec: break
    if lines: parts.append("### "+title+"\n"+"\n".join(lines)+"\n")
  if len(parts)==1: parts.append("（本小时暂无有效更新）")
  parts.append("\n—— 科创研习社专用")
  return "\n".join(parts)

# ---------- 主流程 ----------
def main():
  print("🚀 抓取中 …")
  items=[]
  for u in (EX_RSS+MEDIA_RSS+ECO_RSS): items.extend(fetch_rss(u))
  items.extend(fetch_binance_cms(40))
  for name,base in STATUSPAGES: items.extend(fetch_statuspage(base,name))

  uniq=[]; seen=set()
  for it in items:
    lk=it.get("link","")
    if not lk or lk in seen: continue
    seen.add(lk); uniq.append(it)

  buckets={}
  for it in uniq:
    cat=classify(it); buckets.setdefault(cat,[]).append(it)
  for k in buckets: buckets[k].sort(key=lambda x:(x.get("ts","")), reverse=True)

  md=build_md(buckets, per_sec=10)

  if not PUSHPLUS_TOKEN:
    print("⚠️ 缺少 PUSHPLUS_TOKEN，打印内容：\n", md)
    return
  tokens=[t.strip() for t in PUSHPLUS_TOKEN.split(",") if t.strip()]
  url="https://www.pushplus.plus/send"
  title="【小时快报】去重·中文化·置顶 — 科创研习社专用"
  for tk in tokens:
    try:
      r=requests.post(url,json={"token":tk,"title":title,"content":md,"template":"markdown"},timeout=TIMEOUT)
      print("PushPlus:", tk[:6]+"***", r.status_code, r.text[:120])
    except Exception as e:
      print("PushPlus 异常:", tk[:6]+"***", e)

if __name__=="__main__":
  main()