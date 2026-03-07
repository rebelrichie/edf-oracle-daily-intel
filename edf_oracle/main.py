import requests
import feedparser
import pandas as pd
import os
import json
from datetime import datetime, timedelta
from jinja2 import Template
from groq import Groq
import weasyprint
import re

# ── Markdown stripper ────────────────────────────────────────────────────────
def strip_md(text):
    """Remove markdown links, bold, italic from Groq output before rendering."""
    if not isinstance(text, str):
        return text
    # [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # **bold** -> bold
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    # *italic* -> italic
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    return text.strip()


# ── Credentials ───────────────────────────────────────────────────────────────
SAM_KEY  = os.getenv("SAM_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

# ── Keywords ──────────────────────────────────────────────────────────────────
SAM_KEYWORDS = [
    "daily revisit", "EarthDaily", "GEOINT commercial", "change detection",
    "AI earth observation", "persistent monitoring", "NGA", "Space Force",
    "DIU", "SOCOM", "Army GEOINT"
]

RSS_KEYWORDS = [
    "geospatial", "satellite", "GEOINT", "NGA", "Space Force", "DoD",
    "defense", "remote sensing", "imagery", "EO", "reconnaissance", "DIU",
    "contract", "award", "procurement", "pentagon", "military", "intelligence",
    "drone", "UAV", "ISR", "sensor", "orbit", "launch", "radar", "AI", "data"
]


# ── SAM.gov Opportunities ─────────────────────────────────────────────────────
def get_sam_opps():
    url = "https://api.sam.gov/opportunities/v2/search"
    # Try progressively broader searches until we get results
    keyword_passes = [
        'geospatial OR GEOINT OR "earth observation" OR "remote sensing"',
        'satellite OR imagery OR NGA OR "Space Force" OR surveillance',
        'AI OR "machine learning" OR "change detection" OR "persistent monitoring"',
        'defense OR intelligence OR DoD OR Army OR Navy OR "Air Force"',
    ]
    all_opps = []
    for keywords in keyword_passes:
        params = {
            "api_key"    : SAM_KEY,
            "limit"      : 20,
            "postedFrom" : (datetime.now() - timedelta(days=14)).strftime("%m/%d/%Y"),
            "postedTo"   : datetime.now().strftime("%m/%d/%Y"),
            "keyword"    : keywords
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            print(f"SAM status: {r.status_code} | keywords: {keywords[:40]}")
            if r.ok:
                data = r.json()
                opps = data.get("opportunitiesData", [])
                print(f"  → {len(opps)} results")
                all_opps.extend(opps)
                if len(all_opps) >= 8:
                    break
            else:
                print(f"  → Error body: {r.text[:200]}")
        except Exception as e:
            print(f"SAM error: {e}")

    # Deduplicate by noticeId
    seen = set()
    unique = []
    for o in all_opps:
        nid = o.get("noticeId") or o.get("solicitationNumber") or str(o.get("title",""))
        if nid not in seen:
            seen.add(nid)
            unique.append(o)

    relevant = [o for o in unique if any(k.lower() in str(o).lower() for k in SAM_KEYWORDS)]
    result = relevant if relevant else unique[:8]
    print(f"SAM final: {len(result)} opportunities")
    return result


# ── USASpending Awards ────────────────────────────────────────────────────────
def get_usaspending_awards():
    url     = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    payload = {
        "filters": {
            "time_period": [{
                "start_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "end_date"  : datetime.now().strftime("%Y-%m-%d")
            }],
            "award_type_codes": ["A", "B", "C", "D"],
            "keywords"        : ["geospatial", "GEOINT", "satellite imagery", "earth observation"]
        },
        "fields": ["Award ID", "Recipient Name", "Award Amount", "Description", "Awarding Agency Name"],
        "sort"  : "Award Amount",
        "order" : "desc",
        "limit" : 8,
        "page"  : 1
    }
    headers = {"Content-Type": "application/json", "User-Agent": "EarthDaily-Oracle"}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.ok:
            return [
                {
                    "description"   : item.get("Description") or item.get("Award ID", ""),
                    "recipient_name": item.get("Recipient Name", "Unknown"),
                    "amount"        : item.get("Award Amount", ""),
                    "agency"        : item.get("Awarding Agency Name", "")
                }
                for item in r.json().get("results", [])
            ]
    except Exception as e:
        print(f"USASpending error: {e}")

    return []




# ── Competitor Awards (USASpending) ───────────────────────────────────────────
def get_competitor_awards():
    """Pull recent contract awards to EDF's direct competitors from USASpending."""
    competitors = [
        "Planet Labs", "Planet Federal", "Maxar", "BlackSky",
        "Satellogic", "Umbra", "Capella Space", "HawkEye 360",
        "Palantir", "Esri", "Leica Geosystems"
    ]
    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    results = []

    for comp in competitors[:6]:  # limit API calls
        payload = {
            "filters": {
                "time_period": [{
                    "start_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),
                    "end_date"  : datetime.now().strftime("%Y-%m-%d")
                }],
                "award_type_codes": ["A", "B", "C", "D"],
                "recipient_search_text": [comp]
            },
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Description",
                       "Awarding Agency Name", "Awarding Sub Agency Name",
                       "Period of Performance Start Date"],
            "sort" : "Award Amount",
            "order": "desc",
            "limit": 3,
            "page" : 1
        }
        headers = {"Content-Type": "application/json", "User-Agent": "EarthDaily-Oracle"}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=12)
            if r.ok:
                for item in r.json().get("results", []):
                    amt = item.get("Award Amount", 0) or 0
                    if float(amt) > 50000:  # filter out tiny mods
                        agency = (
                            item.get("Awarding Agency Name") or
                            item.get("Awarding Sub Agency Name") or
                            "DoD"
                        )
                        results.append({
                            "competitor"  : comp,
                            "description" : (item.get("Description") or item.get("Award ID") or "")[:100],
                            "amount"      : float(amt) if amt else 0.0,
                            "agency"      : agency[:50],
                            "date"        : item.get("Period of Performance Start Date", "")
                        })
        except Exception as e:
            print(f"Competitor awards error ({comp}): {e}")

    # Sort by amount desc, return top 6
    results.sort(key=lambda x: float(x.get("amount") or 0), reverse=True)
    print(f"Competitor awards: {len(results)} found")
    return results[:6]



# ── SAM Sources Sought / Pre-Solicitations ────────────────────────────────────
def get_sources_sought():
    """Pull Sources Sought and RFI notices — earlier than awards, still winnable."""
    url = "https://api.sam.gov/opportunities/v2/search"
    results = []
    # Notice types: r=Sources Sought, i=Sources Sought/RFI, p=Presolicitation
    for notice_type in ["r", "p"]:
        params = {
            "api_key"    : SAM_KEY,
            "limit"      : 10,
            "postedFrom" : (datetime.now() - timedelta(days=30)).strftime("%m/%d/%Y"),
            "postedTo"   : datetime.now().strftime("%m/%d/%Y"),
            "ptype"      : notice_type,
            "keyword"    : 'geospatial OR satellite OR imagery OR GEOINT OR "earth observation" OR "remote sensing" OR ISR OR surveillance'
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            print(f"Sources Sought status: {r.status_code} | type: {notice_type}")
            if r.ok:
                opps = r.json().get("opportunitiesData", [])
                print(f"  -> {len(opps)} results")
                for o in opps:
                    results.append({
                        "title"       : o.get("title", ""),
                        "agency"      : o.get("fullParentPathName", ""),
                        "notice_type" : "Sources Sought" if notice_type == "r" else "Pre-Solicitation",
                        "posted"      : o.get("postedDate", ""),
                        "response_due": o.get("responseDeadLine", ""),
                        "link"        : o.get("uiLink", "")
                    })
        except Exception as e:
            print(f"Sources Sought error ({notice_type}): {e}")

    print(f"Sources Sought total: {len(results)}")
    return results[:6]

# ── RSS Feeds ─────────────────────────────────────────────────────────────────
def get_rss():
    feeds = [
        ("Breaking Defense",        "https://breakingdefense.com/feed/"),
        ("Space News",              "https://spacenews.com/feed/"),
        ("Defense News",            "https://www.defensenews.com/rss/"),
        ("Federal News Network",    "https://federalnewsnetwork.com/feed/"),
        ("C4ISRNET",                "https://www.c4isrnet.com/arc/outboundfeeds/rss/"),
        ("Defense One",             "https://www.defenseone.com/rss/all/"),
        ("The War Zone",            "https://www.thedrive.com/the-war-zone/rss"),
        ("Janes",                   "https://www.janes.com/feeds/news"),
        ("Politico Defense",        "https://www.politico.com/rss/defense.xml"),
        ("NextGov",                 "https://www.nextgov.com/rss/all/"),
        ("GovConWire",              "https://www.govconwire.com/feed/"),
        ("ExecutiveBiz",            "https://executivebiz.com/feed/"),
    ]
    articles = []
    for label, feed in feeds:
        try:
            d = feedparser.parse(feed)
            hits = 0
            for entry in d.entries[:15]:
                text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                # Each source gets up to 3 articles max to ensure variety
                if hits >= 3:
                    break
                if any(k.lower() in text for k in RSS_KEYWORDS):
                    articles.append({
                        "title" : entry.title,
                        "link"  : entry.link,
                        "source": label
                    })
                    hits += 1
        except Exception as e:
            print(f"RSS error {label}: {e}")

    return articles[:15]


# ── Groq Summarizer ───────────────────────────────────────────────────────────
def groq_summarize(sam, rss, awards, competitor_awards):
    client = Groq(api_key=GROQ_KEY)

    context = json.dumps({
        "sam_opportunities": [
            {"title": o.get("title",""), "agency": o.get("fullParentPathName",""),
             "type": o.get("type",""), "posted": o.get("postedDate","")}
            for o in sam[:8]
        ],
        "recent_awards": [
            {"recipient": a.get("recipient_name",""), "agency": a.get("agency",""),
             "desc": a.get("description","")[:100], "amount": str(a.get("amount",""))}
            for a in awards[:6]
        ],
        "competitor_awards": [
            {"competitor": c.get("competitor",""), "agency": c.get("agency",""),
             "desc": c.get("description","")[:100], "amount": str(c.get("amount","")),
             "date": c.get("date","")}
            for c in competitor_awards
        ],
        "news_headlines": [a["title"] for a in rss[:10]],
        "sources_sought": [{"title": s.get("title",""), "agency": s.get("agency",""), "type": s.get("notice_type",""), "due": s.get("response_due","")} for s in sources_sought]
    })

    prompt = f"""You are the BD Oracle for EarthDaily Federal.

CRITICAL RULE: Only reference companies, agencies, amounts, and events that appear EXPLICITLY in the DATA below. Do not invent anything. Every claim must trace to a specific item in the data.

ABOUT EDF: Sells AI-generated analysis-ready earth observation data. Daily global coverage, change detection, ML-ready imagery. DATA company not services. Army anchor. Active with NASA, NOAA, DHS. Primes: Deloitte, Leidos, Booz Allen, SAIC, Palantir. Competitors: Planet Labs, Maxar, BlackSky, Satellogic, Umbra. Vehicles: SEWP V, NASA SEWP, GSA MAS, DIU OTA, Army Futures Command OTA, AFWERX, SBIRs, NGA OSINT vehicle, DHS EAGLE II, Army ITES-SW.

RULES:
- competitive: ONLY reference competitors in competitor_awards. State their agency and amount from the data.
- contacts: ONLY reference primes or agencies in recent_awards or sam_opportunities.
- dept_moves: ONLY reference headlines from news_headlines. Give the EDF angle.
- All verbs imperative. Never passive. Never invent.

Return ONLY a valid JSON object. No markdown. No explanation. No code fences. Just the JSON.

The JSON must have exactly these keys: moves_today (array of 3 strings), top_3 (array of 3 strings), contacts (array of 2 strings), dept_moves (array of 2 strings), competitive (array of 2 strings), vehicles (array of 2 strings).

DATA:
{context}"""

    try:
        response = client.chat.completions.create(
            model       = "llama-3.1-8b-instant",
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0.5
        )
        raw    = response.choices[0].message.content.strip()
        raw    = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        moves_today  = [strip_md(x) for x in parsed.get("moves_today",  [])]
        top_3        = [strip_md(x) for x in parsed.get("top_3",        ["No data returned."])]
        contacts     = [strip_md(x) for x in parsed.get("contacts",     [])]
        dept_moves   = [strip_md(x) for x in parsed.get("dept_moves",   [])]
        competitive  = [strip_md(x) for x in parsed.get("competitive",  [])]
        vehicles     = [strip_md(x) for x in parsed.get("vehicles",     [])]
        return (moves_today, top_3, contacts, dept_moves, competitive, vehicles)
    except Exception as e:
        print(f"Groq error: {e}")
        return ([], ["Intel unavailable — check Groq API key or quota."], [], [], [], [])


# ── Main ──────────────────────────────────────────────────────────────────────
sam               = get_sam_opps()
sources_sought    = get_sources_sought()
rss               = get_rss()
awards            = get_usaspending_awards()
competitor_awards = get_competitor_awards()

moves_today, top_3, contacts, dept_moves, competitive, vehicles = groq_summarize(sam, rss, awards, competitor_awards)

print(f"SAM: {len(sam)} opps | Sources Sought: {len(sources_sought)} | Awards: {len(awards)} | Competitors: {len(competitor_awards)} | RSS: {len(rss)} articles")

# Render HTML + PDF
html = Template(open("templates/report.html").read()).render(
    date              = datetime.now().strftime("%B %d, %Y"),
    moves_today       = moves_today,
    top_3             = top_3,
    contacts          = contacts,
    dept_moves        = dept_moves,
    competitive       = competitive,
    vehicles          = vehicles,
    sam               = sam[:8],
    sources_sought    = sources_sought,
    awards            = awards,
    competitor_awards = competitor_awards,
    rss               = rss
)

with open("daily_brief.html", "w") as f:
    f.write(html)

weasyprint.HTML(string=html).write_pdf("daily_brief.pdf")
print("✅ PDF generated")

# HubSpot CSV — SAM first, awards as fallback
rows = []

if sam:
    for opp in sam[:5]:
        title     = opp.get("title") or "New GEOINT Opportunity"
        agency    = opp.get("fullParentPathName") or opp.get("departmentName") or "DoD"
        sol_num   = opp.get("solicitationNumber") or opp.get("noticeId") or ""
        close_raw = opp.get("responseDeadLine") or opp.get("archiveDate") or ""
        try:
            close_dt = datetime.strptime(close_raw[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except Exception:
            close_dt = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        rows.append({
            "Opportunity Name": title[:70],
            "Amount"          : "250000",
            "Close Date"      : close_dt,
            "Stage"           : "Pipeline",
            "Owner"           : "Hunter",
            "Description"     : f"Oracle flagged | {agency} | Sol: {sol_num}" if sol_num else f"Oracle flagged | {agency} | Daily EO fit"
        })

elif awards:
    print("⚠️  SAM returned 0 — falling back to awards for HubSpot CSV")
    for a in awards[:5]:
        rows.append({
            "Opportunity Name": (a.get("description") or "GEOINT Award")[:70],
            "Amount"          : str(a.get("amount", "250000")),
            "Close Date"      : (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"),
            "Stage"           : "Pipeline — Teaming",
            "Owner"           : "Hunter",
            "Description"     : f"Oracle flagged | Prime: {a.get('recipient_name','Unknown')} | {a.get('agency','')} | Sub opportunity"
        })

if rows:
    pd.DataFrame(rows).to_csv("hubspot_import.csv", index=False)
    print(f"✅ HubSpot CSV written — {len(rows)} rows")
else:
    print("⚠️  No data for HubSpot CSV — check SAM API key and quota")

print("✅ Oracle v6 complete — BD Intel Brief generated")
