import requests, feedparser, pandas as pd, os
from datetime import datetime, timedelta
from jinja2 import Template
from groq import Groq
import weasyprint

SAM_KEY = os.getenv("SAM_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")
KEYWORDS = ["daily revisit", "EarthDaily", "GEOINT commercial", "change detection daily", "AI earth observation", "persistent monitoring", "NGA", "Space Force", "DIU", "SOCOM"]

def get_sam_opps():
    url = "https://api.sam.gov/opportunities/v2/search"
    params = {'api_key': SAM_KEY, 'limit': 30, 'postedFrom': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'), 'keyword': 'geospatial OR satellite OR EO OR GEOINT OR "daily revisit"'}
    r = requests.get(url, params=params)
    data = r.json() if r.ok else {}
    opps = data.get('opportunitiesData', [])
    return [opp for opp in opps if any(k.lower() in str(opp).lower() for k in KEYWORDS)]

def get_rss():
    feeds = ["https://breakingdefense.com/feed/", "https://spacenews.com/feed/", "https://www.defensenews.com/rss/"]
    articles = []
    for feed in feeds:
        d = feedparser.parse(feed)
        for entry in d.entries[:5]:
            if any(k.lower() in (entry.title + entry.summary).lower() for k in KEYWORDS):
                articles.append({"title": entry.title, "link": entry.link, "source": feed.split("//")[1].split("/")[0]})
    return articles

def groq_summarize(sam, rss):
    client = Groq(api_key=GROQ_KEY)
    context = f"SAM opps: {len(sam)}\nRSS: {[a['title'] for a in rss]}"
    prompt = """You are the EarthDaily Federal Oracle for DoD sales ONLY. 
    STRICT RULES: ONLY talk about US DoD, NGA, Space Force, DIU, AFWERX, SOCOM, Army or federal defense opportunities. 
    NEVER mention NASA, civilian environmental topics, foreign space programs (India, etc.), or rainforest. 
    Focus ONLY on daily revisit EO, GEOINT, satellite analytics, change detection for defense missions.
    Create exactly 3 bullet points titled "Top 3 Must-Chase Today".
    For each: 1-sentence why it matters for daily 5m EO + one draft outreach sentence to a DoD program manager."""
    response = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt + "\nData: " + context}], temperature=0.7)
    return response.choices[0].message.content.split("\n")

sam = get_sam_opps()
rss = get_rss()
top_3 = groq_summarize(sam, rss)

html = Template(open("templates/report.html").read()).render(date=datetime.now().strftime("%B %d, %Y"), top_3=top_3, sam=sam[:8], rss=rss)

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

print("✅ Oracle complete")
