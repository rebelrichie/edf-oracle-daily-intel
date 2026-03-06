import requests, feedparser, pandas as pd, os, json
from datetime import datetime, timedelta
from jinja2 import Template
from groq import Groq
import weasyprint

SAM_KEY = os.getenv("SAM_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

# ── SAM.gov ──────────────────────────────────────────────────────────────────
def get_sam_opps():
    url = "https://api.sam.gov/opportunities/v2/search"
    params = {
        'api_key': SAM_KEY,
        'limit': 30,
        'postedFrom': (datetime.now() - timedelta(days=7)).strftime('%m/%d/%Y'),
        'keyword': 'geospatial OR satellite OR GEOINT OR "earth observation" OR "remote sensing" OR NGA OR "Space Force"'
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json() if r.ok else {}
        opps = data.get('opportunitiesData', [])
        return opps[:10]  # return more — Groq will filter
    except Exception as e:
        print(f"SAM error: {e}")
        return []

# ── RSS (defense-only feeds) ─────────────────────────────────────────────────
def get_rss():
    feeds = [
        "https://breakingdefense.com/feed/",
        "https://spacenews.com/feed/",
        "https://www.defensenews.com/rss/",
        "https://federalnewsnetwork.com/feed/",
        "https://insidedefense.com/feed"
    ]
    articles = []
    for feed in feeds:
        try:
            d = feedparser.parse(feed)
            for entry in d.entries[:10]:
                text = (entry.get('title', '') + ' ' + entry.get('summary', '')).lower()
                if any(k in text for k in ["geospatial", "satellite", "geoint", "nga", "space force", "diu", "socom", "defense", "eo", "imagery"]):
                    articles.append({
                        "title": entry.title,
                        "link": entry.link,
                        "source": feed.split("//")[1].split("/")[0]
                    })
        except:
            pass
    return articles[:15]

# ── USASpending Awards (robust) ──────────────────────────────────────────────
def get_usaspending_awards():
    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    payload = {
        "filters": {
            "time_period": [{"start_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")}],
            "award_type_codes": ["A", "B", "C", "D"],
            "keywords": ["geospatial", "GEOINT", "satellite imagery", "earth observation", "remote sensing"]
        },
        "fields": ["Award ID", "Recipient Name", "Award Amount", "Description", "Awarding Agency Name"],
        "sort": "Award Amount",
        "order": "desc",
        "limit": 10,
        "page": 1
    }
    headers = {'Content-Type': 'application/json', 'User-Agent': 'EarthDaily-Oracle'}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.ok:
            results = r.json().get("results", [])
            normalized = []
            for item in results:
                normalized.append({
                    "description": item.get("Description") or item.get("Award ID", ""),
                    "recipient_name": item.get("Recipient Name", "Unknown"),
                    "amount": item.get("Award Amount", ""),
                    "agency": item.get("Awarding Agency Name", "")
                })
            return normalized
    except:
        pass
    return []

# ── Groq Deep Analysis (structured JSON output) ──────────────────────────────
def groq_summarize(sam, rss, awards):
    client = Groq(api_key=GROQ_KEY)
    context = json.dumps({
        "sam_opps": [o.get('title') for o in sam[:6]],
        "awards": [{"prime": a.get('recipient_name'), "desc": a.get('description')[:100]} for a in awards],
        "news": [a['title'] for a in rss[:10]]
    }, indent=2)
    prompt = f"""You are EarthDaily Federal Oracle — senior DoD BD strategist. Focus ONLY on defense GEOINT/EO opportunities.
Return ONLY valid JSON — no markdown, no extra text, no fences. Exactly this structure:
{{
  "top_3": [
    "Priority 1: One sentence why EDF should chase this now + draft outreach.",
    "Priority 2: ...",
    "Priority 3: ..."
  ],
  "contacts_teaming": [
    "Reach out to [org/contact] for teaming on [specific opp].",
    "..."
  ],
  "dept_moves": [
    "Pentagon/Agency move: [description] — opportunity for EDF because [reason].",
    "..."
  ],
  "buzz_summary": "One paragraph summarizing key news/competitor moves."
}}
Data: {context}"""
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        return (
            parsed.get("top_3", []),
            parsed.get("contacts_teaming", []),
            parsed.get("dept_moves", []),
            parsed.get("buzz_summary", "No buzz summary")
        )
    except Exception as e:
        print(f"Groq error: {e}")
        return ([], [], [], "Error generating summary")

# ── Main Execution ───────────────────────────────────────────────────────────
sam = get_sam_opps()
rss = get_rss()
awards = get_usaspending_awards()
top_3, contacts, dept_moves, buzz = groq_summarize(sam, rss, awards)

print(f"SAM: {len(sam)} | RSS: {len(rss)} | Awards: {len(awards)}")

html = Template(open("templates/report.html").read()).render(
    date=datetime.now().strftime("%B %d, %Y"),
    top_3=top_3,
    contacts=contacts,
    dept_moves=dept_moves,
    buzz=buzz,
    sam=sam[:8],
    awards=awards,
    rss=rss[:10]
)

with open("daily_brief.html", "w") as f: f.write(html)
weasyprint.HTML(string=html).write_pdf("daily_brief.pdf")

# HubSpot CSV — smarter fallback
rows = []
if sam:
    for opp in sam[:5]:
        title = opp.get('title') or 'New GEOINT Opp'
        agency = opp.get('fullParentPathName') or 'DoD'
        sol = opp.get('solicitationNumber') or ''
        close = opp.get('responseDeadLine') or (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        rows.append({"Opportunity Name": title[:70], "Amount": "250000", "Close Date": close, "Stage": "Pipeline", "Owner": "Hunter", "Description": f"Oracle | {agency} | {sol}"})
elif awards:
    for a in awards[:5]:
        rows.append({"Opportunity Name": (a.get('description') or 'Award')[:70], "Amount": str(a.get('amount', '250000')), "Close Date": (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"), "Stage": "Teaming", "Owner": "Hunter", "Description": f"Oracle | Prime: {a.get('recipient_name')}"})
if rows:
    pd.DataFrame(rows).to_csv("hubspot_import.csv", index=False)
    print(f"HubSpot CSV: {len(rows)} rows")

print("✅ Oracle v6 — deep BD Intel Brief generated")
