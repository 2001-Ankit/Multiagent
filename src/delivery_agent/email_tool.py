import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv(override=True)

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")


@tool
def send_email(to_email: str, subject: str, body: str) -> str:
    """Send an email using the configured Gmail SMTP account."""
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        raise ValueError("EMAIL_ADDRESS and EMAIL_PASSWORD must be set.")
    if not to_email:
        raise ValueError("A recipient email address is required.")

    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.send_message(msg)

    return f"Email sent successfully to {to_email}."


# send_email(
#     to_email="example@@gmail.com",
#     subject="Test Email",
#     body="Hello, this is a test email from Python."
# )
