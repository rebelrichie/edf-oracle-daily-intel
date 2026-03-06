import requests, feedparser, pandas as pd, os
from datetime import datetime, timedelta
from jinja2 import Template
from groq import Groq
import weasyprint

SAM_KEY = os.getenv("SAM_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")
KEYWORDS = ["daily revisit", "EarthDaily", "GEOINT commercial", "change detection daily", "AI earth observation", "persistent monitoring", "NGA", "Space Force", "DIU", "SOCOM", "Army GEOINT"]

def get_sam_opps():
    url = "https://api.sam.gov/opportunities/v2/search"
    params = {'api_key': SAM_KEY, 'limit': 30, 'postedFrom': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'), 'keyword': 'geospatial OR satellite OR EO OR GEOINT OR "daily revisit"'}
    r = requests.get(url, params=params)
    data = r.json() if r.ok else {}
    opps = data.get('opportunitiesData', [])
    return [opp for opp in opps if any(k.lower() in str(opp).lower() for k in KEYWORDS)]

def get_usaspending_awards():
    url = "https://api.usaspending.gov/api/v2/awards/"
    payload = {"filters": {"time_period": [{"start_date": (datetime.now()-timedelta(days=30)).strftime("%Y-%m-%d")}], "keyword": "geospatial OR GEOINT OR satellite OR EO"}}
    headers = {'Content-Type': 'application/json', 'User-Agent': 'EarthDaily-Oracle'}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.ok:
            return r.json().get("results", [])[:8]
    except:
        pass
    return []

def get_rss():
    feeds = ["https://breakingdefense.com/feed/", "https://spacenews.com/feed/", "https://www.defensenews.com/rss/", "https://insidedefense.com/feed", "https://federalnewsnetwork.com/feed/"]
    articles = []
    for feed in feeds:
        d = feedparser.parse(feed)
        for entry in d.entries[:8]:
            if any(k.lower() in (entry.title + entry.summary).lower() for k in KEYWORDS):
                articles.append({"title": entry.title, "link": entry.link, "source": feed.split("//")[1].split("/")[0]})
    return articles

def groq_summarize(sam, rss, awards):
    client = Groq(api_key=GROQ_KEY)
    context = f"SAM opps: {len(sam)}\nRecent awards: {awards}\nNews: {[a['title'] for a in rss]}"
    prompt = """You are the EarthDaily Federal Oracle — a senior DoD BD strategist. STRICT DEFENSE FOCUS ONLY.
    Output in this exact structure (no extra text):
    **Top 3 Must-Chase Today**
    - bullet 1: why daily 5m EO matters + draft outreach sentence
    - bullet 2: ...
    - bullet 3: ...
    **Potential Contacts & Teaming Plays**
    - list 2-4 real primes or liaisons from awards/news (e.g., "Reach out to smallbusiness@nga.mil" or "Team with [prime name]")
    **Key Departmental Moves**
    - 2-3 new RFIs, reorganizations, or budget shifts that create opportunities
    **Relevant News & Competitor Moves**
    - 3-4 bullet points from RSS with why they matter"""
    response = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt + "\nData: " + context}], temperature=0.6)
    return response.choices[0].message.content.split("\n")

sam = get_sam_opps()
rss = get_rss()
awards = get_usaspending_awards()
top_3 = groq_summarize(sam, rss, awards)

html = Template(open("templates/report.html").read()).render(
    date=datetime.now().strftime("%B %d, %Y"),
    top_3=top_3,
    sam=sam[:8],
    awards=awards,
    rss=rss
)

with open("daily_brief.html", "w") as f: f.write(html)
weasyprint.HTML(string=html).write_pdf("daily_brief.pdf")

n = min(5, len(sam))
df = pd.DataFrame({
    "Opportunity Name": [f"EDF Oracle – {opp.get('title','New GEOINT')[:60]}" for opp in sam[:n]],
    "Amount": ["250000"] * n,
    "Close Date": [(datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")] * n,
    "Stage": ["Pipeline"] * n,
    "Owner": ["Hunter"] * n,
    "Description": ["Oracle flagged – daily EO fit"] * n
})
df.to_csv("hubspot_import.csv", index=False)

print("✅ Oracle v5 complete — deep strategic report")
