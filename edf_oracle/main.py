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
        'postedFrom': (datetime.now() - timedelta(days=3)).strftime('%m/%d/%Y'),
        'keyword': 'geospatial OR satellite OR GEOINT OR "daily revisit" OR "earth observation"'
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json() if r.ok else {}
        opps = data.get('opportunitiesData', [])
        return [opp for opp in opps if any(k.lower() in str(opp).lower() for k in SAM_KEYWORDS)]
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

# HubSpot CSV
n = min(5, len(sam))
if n > 0:
    df = pd.DataFrame({
        "Opportunity Name": [f"EDF Oracle – {opp.get('title','New GEOINT')[:60]}" for opp in sam[:n]],
        "Amount": ["250000"] * n,
        "Close Date": [(datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")] * n,
        "Stage": ["Pipeline"] * n,
        "Owner": ["Hunter"] * n,
        "Description": ["Oracle flagged – daily EO fit"] * n
    })
    df.to_csv("hubspot_import.csv", index=False)
    print(f"✅ HubSpot CSV written — {n} opportunities")

print("✅ Oracle v6 complete — BD Intel Brief generated")
