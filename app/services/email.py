"""
Send notifications via SMTP (Gmail-compatible). No-op if credentials are not set.
"""
import logging
import smtplib
from html import escape
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def _smtp_ready() -> bool:
    return bool(
        settings.EMAIL_SMTP_HOST.strip()
        and settings.EMAIL_SMTP_USERNAME.strip()
        and settings.EMAIL_SMTP_PASSWORD.strip()
    )


def send_notification(
    recipient_email: str | None,
    title: str,
    body: str,
    suggested_action: str | None = None,
    *,
    allow_default_recipient: bool = True,
    skip_sender_recipient: bool = False,
) -> bool:
    """Send an email notification. Returns True if sent, False if skipped/failed."""
    to_email = (
        (recipient_email or "").strip()
        if not allow_default_recipient
        else (recipient_email or settings.EMAIL_DEFAULT_TO).strip()
    )
    if not to_email:
        return False
    if not _smtp_ready():
        return False

    from_email = (settings.EMAIL_FROM or settings.EMAIL_SMTP_USERNAME).strip()
    if not from_email:
        return False
    smtp_sender = settings.EMAIL_SMTP_USERNAME.strip().lower()
    if skip_sender_recipient and to_email.lower() in {from_email.lower(), smtp_sender}:
        logger.info("Email skipped because recipient matches sender account: %s", to_email)
        return False

    text = body
    if suggested_action:
        text = f"{body}\n\nSuggested action: {suggested_action}"

    html = _render_html_notification(title=title, body=body, suggested_action=suggested_action)

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(settings.EMAIL_SMTP_HOST.strip(), settings.EMAIL_SMTP_PORT) as server:
            if settings.EMAIL_SMTP_STARTTLS:
                server.starttls()
            server.login(settings.EMAIL_SMTP_USERNAME.strip(), settings.EMAIL_SMTP_PASSWORD.strip())
            server.send_message(msg)
        logger.info("Email notification sent to %s", to_email)
        return True
    except Exception as e:
        logger.exception("Email send failed to %s: %s", to_email, e)
        return False


def _render_html_notification(title: str, body: str, suggested_action: str | None) -> str:
    sections = _markdown_sections(body)
    cards = []
    for heading, items in sections:
        rendered_items = "".join(
            f"<li style='margin:0.25rem 0;color:#dbe7ff;line-height:1.45;'>{escape(item)}</li>" for item in items
        )
        cards.append(
            "<section class='mail-section' style='background:#141c2f;border:1px solid #2b3758;border-radius:12px;padding:14px 16px;margin:0 0 12px;'>"
            f"<h3 style='margin:0 0 10px;font-size:15px;color:#f8fbff;'>{escape(heading)}</h3>"
            f"<ul style='margin:0;padding-left:18px'>{rendered_items or '<li style=\"color:#9ab0d5\">No updates.</li>'}</ul>"
            "</section>"
        )
    badge = ""
    if suggested_action:
        badge = (
            "<p style='margin:0 0 14px;'>"
            "<span style='display:inline-block;background:#1d4ed8;color:#eff6ff;border-radius:999px;padding:6px 12px;font-size:12px;font-weight:600;'>"
            f"Suggested Action: {escape(suggested_action)}"
            "</span></p>"
        )
    body_html = "".join(cards) or (
        "<section class='mail-section' style='background:#141c2f;border:1px solid #2b3758;border-radius:12px;padding:14px 16px;'>"
        f"<p style='margin:0;color:#dbe7ff;line-height:1.5;'>{escape(body)}</p>"
        "</section>"
    )
    return (
        "<!doctype html><html><head>"
        "<meta name='viewport' content='width=device-width, initial-scale=1' />"
        "<style>"
        "body{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}"
        ".mail-wrap{width:100%;max-width:700px;margin:0 auto;background:#0f172a;border:1px solid #25304d;border-radius:16px;padding:16px;box-sizing:border-box;}"
        ".mail-section{background:#141c2f;border:1px solid #2b3758;border-radius:12px;padding:14px 16px;margin:0 0 12px;}"
        "@media (max-width: 600px){"
        "body{padding:6px !important;}"
        ".mail-wrap{padding:10px !important;border-radius:10px !important;}"
        ".mail-section{padding:8px 10px !important;margin-bottom:6px !important;}"
        "h2{font-size:18px !important;line-height:1.25 !important;}"
        "h3{font-size:14px !important;}"
        "li,p{font-size:14px !important;line-height:1.35 !important;}"
        "}"
        "</style></head><body style='margin:0;background:#0b1220;padding:24px;font-family:Segoe UI,Arial,sans-serif;'>"
        "<div class='mail-wrap'>"
        f"<h2 style='margin:0 0 6px;color:#ffffff;font-size:22px;'>{escape(title)}</h2>"
        "<p style='margin:0 0 16px;color:#94a3b8;font-size:13px;'>Portfolio-aware market notification</p>"
        f"{badge}{body_html}"
        "</div></body></html>"
    )


def _markdown_sections(markdown_text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_heading = "Update"
    current_items: list[str] = []
    for raw_line in (markdown_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            if current_items:
                sections.append((current_heading, current_items))
            current_heading = line[3:].strip() or "Update"
            current_items = []
            continue
        if line.startswith("### "):
            current_items.append(f"Asset: {line[4:].strip()}")
            continue
        if line.startswith(("- ", "* ")):
            current_items.append(line[2:].strip())
        else:
            current_items.append(line)
    if current_items:
        sections.append((current_heading, current_items))
    return sections
