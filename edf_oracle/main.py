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
    url    = "https://api.sam.gov/opportunities/v2/search"
    params = {
        "api_key"    : SAM_KEY,
        "limit"      : 30,
        "postedFrom" : (datetime.now() - timedelta(days=7)).strftime("%m/%d/%Y"),
        "keyword"    : 'geospatial OR satellite OR GEOINT OR "earth observation" OR "remote sensing" OR NGA OR "Space Force"'
    }
    try:
        r    = requests.get(url, params=params, timeout=15)
        data = r.json() if r.ok else {}
        opps = data.get("opportunitiesData", [])

        relevant = [o for o in opps if any(k.lower() in str(o).lower() for k in SAM_KEYWORDS)]
        return relevant if relevant else opps[:8]

    except Exception as e:
        print(f"SAM error: {e}")
        return []


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
def groq_summarize(sam, rss, awards):
    client  = Groq(api_key=GROQ_KEY)
    context = json.dumps({
        "sam_count"      : len(sam),
        "sam_titles"     : [o.get("title", "") for o in sam[:5]],
        "awards"         : [{"recipient": a.get("recipient_name"), "desc": a.get("description", "")[:80]} for a in awards[:5]],
        "news_headlines" : [a["title"] for a in rss[:8]]
    })

    prompt = f"""You are the BD Oracle for EarthDaily Federal. You think like a senior IC-cleared business developer with 15 years selling data and platforms to the intelligence community and DoD.

ABOUT EARTHDAILY FEDERAL:
EarthDaily Federal sells AI-generated, analysis-ready earth observation data. Daily global coverage, change detection, and ML-ready imagery products built on the EarthDaily constellation. Their edge: daily revisit frequency, AI-ready pipelines, and automated change detection that replaces analyst-hours. DATA company, not services.

CURRENT BASE:
- Army is the anchor — strong existing relationships, push for expansion
- Active with NASA, NOAA, DHS, all military branches
- Primes: Deloitte, Leidos, Booz Allen, SAIC, Palantir — EDF subs data to them
- Both direct contracts and prime subs in play
- Competitors to watch: Planet Labs, Maxar, BlackSky, Satellogic, Umbra

PROCUREMENT VEHICLES EDF CAN USE:
- SEWP V, NASA SEWP, GSA MAS Schedule 70
- OTAs through DIU, Army Futures Command, AFWERX
- SBIRs via DoD, NASA, NOAA
- NGA OSINT/Commercial GEOINT vehicles
- DHS EAGLE II, Army ITES-SW

WHAT TRIGGERS A REAL OPPORTUNITY:
- Any IC/DoD program needing persistent monitoring, change detection, or daily EO
- Primes who just won GEOINT, ISR, or AI/ML contracts — they need a commercial data sub now
- New PM or contracting officer appointments at NGA, NRO, SOCOM, DIA, Space Force
- Competitor loss or contract expiration — Planet or Maxar losing an incumbent = open window
- Budget increases for AI/ML, GEOINT, or ISR at any agency
- Sources sought, RFIs, pre-solicitation notices — earlier than awards, still winnable
- Set-asides (SBIR, 8a, small biz) where EDF can prime or sub strategically

WHAT TO IGNORE:
Pure IT services, cybersecurity, ground systems with no data angle.

YOUR JOB:
Write like a war room briefing. Imperative verbs only — "Reach out", "Target", "Monitor", "Flag", "Position", "Contact", "Watch", "Call". Never passive. Every item must be something that cannot be googled — connect dots between the data, name the specific angle for EDF.

Return ONLY valid JSON. No markdown, no extra text, no code fences. Exactly this structure:

{{
  "moves_today": [
    "One action to take TODAY — make a call, send an email. One sentence, imperative, specific org/person.",
    "Second action for today. Same standard.",
    "Third action for today. Same standard."
  ],
  "top_3": [
    "MAX 2 sentences. Specific opportunity, why it maps to EDF data, what the move is. Imperative verb. No URLs.",
    "MAX 2 sentences. Same standard.",
    "MAX 2 sentences. Same standard."
  ],
  "contacts": [
    "One sentence. Specific org or prime to reach, what they just won or need, why EDF data fits now. No URLs.",
    "One sentence. Same standard."
  ],
  "dept_moves": [
    "One sentence. Budget shift, new appointment, RFI, or reorg — specific angle for EDF this week. No URLs.",
    "One sentence. Same standard."
  ],
  "competitive": [
    "One sentence. What a competitor (Planet, Maxar, BlackSky, Satellogic) just did and what it means for EDF. No URLs.",
    "One sentence. Same standard."
  ],
  "vehicles": [
    "One sentence. Specific contract vehicle or set-aside EDF should use to pursue something in today's data. No URLs.",
    "One sentence. Same standard."
  ]
}}

Data: {context}"""

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
sam    = get_sam_opps()
rss    = get_rss()
awards = get_usaspending_awards()

moves_today, top_3, contacts, dept_moves, competitive, vehicles = groq_summarize(sam, rss, awards)

print(f"SAM: {len(sam)} opps | Awards: {len(awards)} | RSS: {len(rss)} articles")

# Render HTML + PDF
html = Template(open("templates/report.html").read()).render(
    date        = datetime.now().strftime("%B %d, %Y"),
    moves_today = moves_today,
    top_3       = top_3,
    contacts    = contacts,
    dept_moves  = dept_moves,
    competitive = competitive,
    vehicles    = vehicles,
    sam         = sam[:8],
    awards      = awards,
    rss         = rss
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
