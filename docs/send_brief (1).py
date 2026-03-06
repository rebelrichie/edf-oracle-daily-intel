"""
send_brief.py — Email the daily BD Intel Brief PDF + link to live dashboard.
"""
import os, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.mime.base      import MIMEBase
from email                import encoders
from datetime             import datetime

GMAIL_USER         = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
SEND_TO            = [e.strip() for e in os.environ.get("SEND_TO","").split(",") if e.strip()]
CC_LIST            = [e.strip() for e in os.environ.get("BRIEF_CC","").split(",") if e.strip()]
SITE_URL           = os.environ.get("SITE_URL", "")

today   = datetime.now().strftime("%B %d, %Y")
subject = f"EDF BD Intel Brief — {today}"

site_line = f'<p style="margin:16px 0;"><a href="{SITE_URL}" style="color:#7CCBC3;font-family:monospace;">🌐 Open Live Dashboard →</a></p>' if SITE_URL else ""

html_body = f"""
<div style="font-family:sans-serif;background:#050d1b;color:#d8e8f4;padding:32px;border-radius:10px;max-width:600px;">
  <div style="font-size:10px;letter-spacing:0.2em;color:#7CCBC3;text-transform:uppercase;margin-bottom:8px;">EarthDaily Federal · Intelligence Operations</div>
  <h1 style="font-size:28px;font-weight:800;color:#fff;margin:0 0 16px;">BD Intel Brief</h1>
  <p style="color:#6a8aaa;font-size:13px;margin-bottom:16px;">{today}</p>
  <p style="font-size:13px;line-height:1.7;margin-bottom:20px;">Your daily BD brief is attached. Top opportunities, competitive landscape, procurement vehicles, and industry buzz — live from SAM.gov, USASpending, and defense news feeds.</p>
  {site_line}
  <hr style="border:none;border-top:1px solid rgba(124,203,195,0.2);margin:24px 0;">
  <p style="font-size:10px;color:#3d5570;">Oracle · EarthDaily Federal · Automated BD Intelligence</p>
</div>"""

msg = MIMEMultipart("alternative")
msg["Subject"] = subject
msg["From"]    = GMAIL_USER
msg["To"]      = ", ".join(SEND_TO)
if CC_LIST: msg["Cc"] = ", ".join(CC_LIST)
msg.attach(MIMEText(html_body, "html"))

for path, label in [("daily_brief.pdf", f"EDF_BD_Intel_{datetime.now().strftime('%Y%m%d')}.pdf"),
                     ("hubspot_import.csv", f"EDF_HubSpot_{datetime.now().strftime('%Y%m%d')}.csv")]:
    if os.path.exists(path):
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{label}"')
            msg.attach(part)
        print(f"✅ Attached: {path}")

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, SEND_TO + CC_LIST, msg.as_string())
    print(f"✅ Sent to: {', '.join(SEND_TO + CC_LIST)}")
except Exception as e:
    print(f"❌ Email error: {e}"); raise
