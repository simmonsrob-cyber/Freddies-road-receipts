"""Email the aircraft commander. Standard library only."""
import smtplib
import ssl
from email.message import EmailMessage

import config


def configured():
    return bool(config.SMTP_USER and config.SMTP_PASSWORD and config.MAIL_TO and config.MAIL_FROM)


def send(subject, body, attach_path=None):
    """Return None on success, or a readable error message."""
    if not configured():
        return "Email is not set up yet. Fill in the SMTP lines in the .env file on the Pi."
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, config.MAIL_FROM, ", ".join(config.MAIL_TO)
    msg.set_content(body)
    if attach_path:
        data = open(attach_path, "rb").read()
        msg.add_attachment(data, maintype="application", subtype="zip", filename=attach_path.name)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=60) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        return "The email server did not accept the login. Check the app password in the .env file."
    except (smtplib.SMTPException, OSError) as e:
        return "The email could not be sent (%s). The zip was saved; you can try again." % type(e).__name__
    return None
