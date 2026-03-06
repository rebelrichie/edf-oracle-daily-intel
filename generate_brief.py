import requests, feedparser, pandas as pd, os, json
from datetime import datetime, timedelta
from jinja2 import Template
from groq import Groq
import weasyprint

SAM_KEY = os.getenv("SAM_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

# Broader keyword set — used for SAM filtering only
SAM_KEYWORDS = [
    "daily revisit", "EarthDaily", "GEOINT commercial", "change detection",
    "AI earth observation", "persistent monitoring", "NGA", "Space Force",
    "DIU", "SOCOM", "Army GEOINT"
]

# Loose RSS keywords — just enough to stay defense/space relevant
RSS_KEYWORDS = [
    "geospatial", "satellite", "GEOINT", "NGA", "Space Force", "DoD",
    "defense", "remote sensing", "imagery", "EO", "reconnaissance", "DIU"
]


# ── SAM.gov ──────────────────────────────────────────────────────────────────
def get_sam_opps():
    url = "https://api.sam.gov/opportunities/v2/search"
    params = {
        'api_key': SAM_KEY,
        'limit': 30,
        'postedFrom': (datetime.now() - timedelta(days=7)).strftime('%m/%d/%Y'),  # widen to 7 days
        'keyword': 'geospatial OR satellite OR GEOINT OR "earth observation" OR "remote sensing" OR NGA OR "Space Force"'
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json() if r.ok else {}
        opps = data.get('opportunitiesData', [])
        # Filter for keyword relevance but with a broader check
        relevant = [opp for opp in opps if any(k.lower() in str(opp).lower() for k in SAM_KEYWORDS)]
        # If strict filter returns nothing, return everything from the search
        return relevant if relevant else opps[:8]
    except Exception as e:
        print(f"SAM error: {e}")
        return []


# ── USASpending Awards ────────────────────────────────────────────────────────
def get_usaspending_awards():
    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    payload = {
        "filters": {
            "time_period": [{
                "start_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "end_date": datetime.now().strftime("%Y-%m-%d")
            }],
            "award_type_codes": ["A", "B", "C", "D"],
            "keywords": ["geospatial", "GEOINT", "satellite imagery", "earth observation"]
        },
        "fields": ["Award ID", "Recipient Name", "Award Amount", "Description", "Awarding Agency Name"],
        "sort": "Award Amount",
        "order": "desc",
        "limit": 8,
        "page": 1
    }
    headers = {'Content-Type': 'application/json', 'User-Agent': 'EarthDaily-Oracle'}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.ok:
            results = r.json().get("results", [])
            # Normalize field names to match template expectations
            normalized = []
            for item in results:
                normalized.append({
                    "description": item.get("Description") or item.get("Award ID", ""),
                    "recipient_name": item.get("Recipient Name", "Unknown"),
                    "amount": item.get("Award Amount", ""),
                    "agency": item.get("Awarding Agency Name", "")
                })
            return normalized
    except Exception as e:
        print(f"USASpending error: {e}")
    return []


# ── RSS ───────────────────────────────────────────────────────────────────────
def get_rss():
    feeds = [
        "https://breakingdefense.com/feed/",
        "https://spacenews.com/feed/",
        "https://www.defensenews.com/rss/",
        "https://federalnewsnetwork.com/feed/",
        "https://www.c4isrnet.com/arc/outboundfeeds/rss/"
    ]
    articles = []
    for feed in feeds:
        try:
            d = feedparser.parse(feed)
            for entry in d.entries[:10]:
                text = (entry.get('title', '') + ' ' + entry.get('summary', '')).lower()
                if any(k.lower() in text for k in RSS_KEYWORDS):
                    articles.append({
                        "title": entry.title,
                        "link": entry.link,
                        "source": feed.split("//")[1].split("/")[0]
                    })
        except Exception as e:
            print(f"RSS error {feed}: {e}")
    return articles[:10]


# ── Groq ──────────────────────────────────────────────────────────────────────
def groq_summarize(sam, rss, awards):
    client = Groq(api_key=GROQ_KEY)

    context = json.dumps({
        "sam_count": len(sam),
        "sam_titles": [o.get('title', '') for o in sam[:5]],
        "awards": [{"recipient": a.get('recipient_name'), "desc": a.get('description', '')[:80]} for a in awards[:5]],
        "news_headlines": [a['title'] for a in rss[:8]]
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
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        raw = response.choices[0].message.content.strip()
        # Strip any accidental markdown fences
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        return (
            parsed.get("top_3", ["No data returned."]),
            parsed.get("contacts", []),
            parsed.get("dept_moves", [])
        )
    except Exception as e:
        print(f"Groq parse error: {e}\nRaw: {raw if 'raw' in dir() else 'no response'}")
        return (["Intel unavailable — check Groq API key or quota."], [], [])


# ── Main ──────────────────────────────────────────────────────────────────────
sam     = get_sam_opps()
rss     = get_rss()
awards  = get_usaspending_awards()

top_3, contacts, dept_moves = groq_summarize(sam, rss, awards)

print(f"SAM: {len(sam)} opps | Awards: {len(awards)} | RSS: {len(rss)} articles")
print(f"Top 3: {top_3}")

html = Template(open("templates/report.html").read()).render(
    date=datetime.now().strftime("%B %d, %Y"),
    top_3=top_3,
    contacts=contacts,
    dept_moves=dept_moves,
    sam=sam[:8],
    awards=awards,
    rss=rss
)

with open("daily_brief.html", "w") as f:
    f.write(html)

weasyprint.HTML(string=html).write_pdf("daily_brief.pdf")

# HubSpot CSV — use SAM opps if available, fall back to awards data
rows = []

if sam:
    for opp in sam[:5]:
        title = opp.get('title') or opp.get('opportunityTitle') or 'New GEOINT Opportunity'
        agency = opp.get('fullParentPathName') or opp.get('departmentName') or 'DoD'
        sol_num = opp.get('solicitationNumber') or opp.get('noticeId') or ''
        close_raw = opp.get('responseDeadLine') or opp.get('archiveDate') or ''
        try:
            close_dt = datetime.strptime(close_raw[:10], "%Y-%m-%d").strftime("%Y-%m-%d") if close_raw else (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        except Exception:
            close_dt = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        rows.append({
            "Opportunity Name": title[:70],
            "Amount": "250000",
            "Close Date": close_dt,
            "Stage": "Pipeline",
            "Owner": "Hunter",
            "Description": f"Oracle flagged | {agency} | Sol: {sol_num}" if sol_num else f"Oracle flagged | {agency} | Daily EO fit"
        })
    print(f"HubSpot source: SAM ({len(rows)} opps)")

elif awards:
    # SAM returned nothing — fall back to recent awards as teaming pipeline entries
    for a in awards[:5]:
        rows.append({
            "Opportunity Name": (a.get('description') or 'GEOINT Award')[:70],
            "Amount": str(a.get('amount', '250000')),
            "Close Date": (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"),
            "Stage": "Pipeline — Teaming",
            "Owner": "Hunter",
            "Description": f"Oracle flagged | Prime: {a.get('recipient_name','Unknown')} | {a.get('agency','')} | Sub opportunity"
        })
    print(f"HubSpot source: awards fallback ({len(rows)} rows — SAM returned 0)")

if rows:
    df = pd.DataFrame(rows)
    df.to_csv("hubspot_import.csv", index=False)
    print(f"✅ HubSpot CSV written — {len(rows)} rows")
else:
    print("⚠️  No data for HubSpot CSV — check SAM API key and quota")

print("✅ Oracle v6 complete — BD Intel Brief generated")
