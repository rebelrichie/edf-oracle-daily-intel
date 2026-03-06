import requests
import feedparser
import pandas as pd
import os
import json
from datetime import datetime, timedelta
from jinja2 import Template
from groq import Groq
import weasyprint

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

    prompt = f"""You are the EarthDaily Federal Oracle — a senior DoD BD strategist focused on geospatial, GEOINT, and earth observation contracts.

Return ONLY valid JSON. No markdown, no extra text, no code fences. Exactly this structure:

{{
  "top_3": [
    "One sentence describing the highest priority opportunity and why EDF should move on it now.",
    "One sentence for the second priority.",
    "One sentence for the third priority."
  ],
  "contacts": [
    "Specific teaming or outreach action with a real org or email from the data.",
    "Second contact/teaming play."
  ],
  "dept_moves": [
    "One RFI, budget shift, or reorganization that creates an opening.",
    "Second departmental move."
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
        return (
            parsed.get("top_3",      ["No data returned."]),
            parsed.get("contacts",   []),
            parsed.get("dept_moves", [])
        )
    except Exception as e:
        print(f"Groq error: {e}")
        return (["Intel unavailable — check Groq API key or quota."], [], [])


# ── Main ──────────────────────────────────────────────────────────────────────
sam    = get_sam_opps()
rss    = get_rss()
awards = get_usaspending_awards()

top_3, contacts, dept_moves = groq_summarize(sam, rss, awards)

print(f"SAM: {len(sam)} opps | Awards: {len(awards)} | RSS: {len(rss)} articles")

# Render HTML + PDF
html = Template(open("templates/report.html").read()).render(
    date       = datetime.now().strftime("%B %d, %Y"),
    top_3      = top_3,
    contacts   = contacts,
    dept_moves = dept_moves,
    sam        = sam[:8],
    awards     = awards,
    rss        = rss
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
