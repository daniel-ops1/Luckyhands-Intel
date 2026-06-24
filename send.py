import smtplib
import ssl
from email.message import EmailMessage

from config import (
    RECIPIENT_EMAIL,
    SENDER_EMAIL,
    SENDER_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)


def send_email(subject: str, html: str) -> None:
    if not SMTP_USER or not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP_USER and SMTP_PASSWORD are not set, fill in .env to send email"
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = RECIPIENT_EMAIL
    msg.set_content(
        "This email is best viewed as HTML. If you see this, your client is rendering plain text."
    )
    msg.add_alternative(html, subtype="html")

    print(f"sending to {RECIPIENT_EMAIL} via {SMTP_HOST}:{SMTP_PORT}")
    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=context)
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
    print("sent")
