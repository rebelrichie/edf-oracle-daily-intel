import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime

SEND_TO        = os.environ["SEND_TO"]
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
BRIEF_CC       = os.environ.get("BRIEF_CC", "")   # optional, won't break if not set

today = datetime.now().strftime("%B %d, %Y")

msg = MIMEMultipart()
msg["From"]    = f"Oracle Intel <{GMAIL_USER}>"
msg["To"]      = SEND_TO
if BRIEF_CC:
    msg["Cc"]  = BRIEF_CC
msg["Subject"] = f"BD Intel Brief — {today}"

body = MIMEText(f"""Your daily BD Intel Brief is attached.

{today} | Powered by Groq AI · Deep Strategic Edition
EarthDaily Federal · Intelligence Operations

— Oracle
""", "plain")
msg.attach(body)

# Attach PDF
pdf_path = "daily_brief.pdf"
if os.path.exists(pdf_path):
    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="BD_Intel_Brief_{today.replace(" ", "_").replace(",", "")}.pdf"')
    msg.attach(part)
    print(f"✅ PDF attached: {pdf_path}")
else:
    print("⚠️  PDF not found — sending without attachment")

# Attach HubSpot CSV if it exists
csv_path = "hubspot_import.csv"
if os.path.exists(csv_path):
    with open(csv_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="HubSpot_Import_{today.replace(" ", "_").replace(",", "")}.csv"')
    msg.attach(part)
    print(f"✅ HubSpot CSV attached: {csv_path}")

# Send
try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        recipients = [SEND_TO] + ([BRIEF_CC] if BRIEF_CC else [])
        server.sendmail(GMAIL_USER, recipients, msg.as_string())
        sent_to = ", ".join(recipients)
    print(f"✅ Brief sent to {sent_to}")
except Exception as e:
    print(f"❌ Email failed: {e}")
    raise
