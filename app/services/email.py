"""
Send notifications via SMTP (Gmail-compatible). No-op if credentials are not set.
"""
import logging
import smtplib
from html import escape
from email.message import EmailMessage

import bleach
import markdown

from app.core.config import settings

logger = logging.getLogger(__name__)

# Mirrors frontend/app/globals.css :root — email-safe hex (no color-mix()).
_MAIL_THEME = {
    "bg": "#070b12",
    "bg_elevated": "#0c1220",
    "surface": "#111827",
    "surface_2": "#1e293b",
    "border": "#2d3a52",
    "border_strong": "#3d4f6f",
    "text": "#f1f5f9",
    "muted": "#94a3b8",
    "accent": "#38bdf8",
    "accent_hover": "#7dd3fc",
    "accent_dim": "#0ea5e9",
    "code_bg": "rgba(255, 255, 255, 0.08)",
    "blockquote_bg": "rgba(56, 189, 248, 0.08)",
}

_MAIL_MD_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "strong",
        "em",
        "code",
        "pre",
        "blockquote",
        "a",
        "hr",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)

_MAIL_MD_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel"],
    "code": ["class"],
    "th": ["align", "colspan", "rowspan"],
    "td": ["align", "colspan", "rowspan"],
}


def _smtp_ready() -> bool:
    return bool(
        settings.EMAIL_SMTP_HOST.strip()
        and settings.EMAIL_SMTP_USERNAME.strip()
        and settings.EMAIL_SMTP_PASSWORD.strip()
    )


def _markdown_to_safe_html(markdown_text: str) -> str:
    """Render GFM-like markdown to HTML and strip unsafe tags (parity with chat MarkdownMessage)."""
    text = (markdown_text or "").strip()
    if not text:
        return f"<p class='mail-muted' style='margin:0;color:{_MAIL_THEME['muted']};'>No content.</p>"

    md = markdown.Markdown(
        extensions=[
            "markdown.extensions.fenced_code",
            "markdown.extensions.tables",
            "markdown.extensions.nl2br",
            "markdown.extensions.sane_lists",
        ],
        output_format="html5",
    )
    raw_html = md.convert(text)
    return bleach.clean(
        raw_html,
        tags=_MAIL_MD_ALLOWED_TAGS,
        attributes=_MAIL_MD_ALLOWED_ATTRS,
        protocols=("http", "https", "mailto"),
        strip=True,
    )


def _mail_styles() -> str:
    t = _MAIL_THEME
    return f"""
body {{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}
.mail-page {{ margin:0;background:{t['bg']};padding:24px 16px;font-family:system-ui,-apple-system,'Segoe UI',Arial,sans-serif; }}
.mail-wrap {{
  width:100%;max-width:700px;margin:0 auto;background:{t['surface']};
  border:1px solid {t['border']};border-radius:16px;padding:20px 22px;box-sizing:border-box;
  box-shadow:0 18px 50px rgba(0,0,0,0.45),0 0 0 1px rgba(56,189,248,0.06);
}}
.mail-title {{
  margin:0 0 8px;font-size:22px;font-weight:650;letter-spacing:-0.02em;line-height:1.2;
  color:{t['text']};
  border-left:3px solid {t['accent']};padding:0 0 12px 14px;margin-left:0;
  border-bottom:1px solid {t['border']};
}}
.mail-subtitle {{ margin:0 0 18px;color:{t['muted']};font-size:13px;line-height:1.45; }}
.mail-badge-wrap {{ margin:0 0 16px; }}
.mail-badge {{
  display:inline-block;background:linear-gradient(135deg,{t['accent_dim']},#0369a1);color:#f8fafc;
  border-radius:999px;padding:8px 14px;font-size:12px;font-weight:600;
  border:1px solid rgba(125,211,252,0.35);box-shadow:0 4px 14px rgba(14,165,233,0.25);
}}
.mail-body {{
  background:{t['bg_elevated']};
  border:1px solid {t['border']};border-radius:14px;padding:16px 18px;
  color:{t['text']};font-size:15px;line-height:1.55;word-break:break-word;
}}
/* Markdown inside email — aligned with frontend .md */
.mail-md > :first-child {{ margin-top:0; }}
.mail-md > :last-child {{ margin-bottom:0; }}
.mail-md p {{ margin:0 0 0.7rem; color:{t['text']}; }}
.mail-md h1,.mail-md h2,.mail-md h3,.mail-md h4,.mail-md h5,.mail-md h6 {{
  font-weight:650;line-height:1.25;margin:1.1rem 0 0.55rem;color:{t['text']};
}}
.mail-md h1 {{ font-size:1.35rem; margin-top:0.4rem; }}
.mail-md h2 {{ font-size:1.2rem; }}
.mail-md h3 {{ font-size:1.05rem; }}
.mail-md h4 {{ font-size:0.98rem; }}
.mail-md h5,.mail-md h6 {{ font-size:0.92rem;color:{t['muted']}; }}
.mail-md ul,.mail-md ol {{ margin:0 0 0.8rem;padding-left:1.35rem; }}
.mail-md li {{ margin-bottom:0.3rem;color:{t['text']}; }}
.mail-md li > p {{ margin-bottom:0.3rem; }}
.mail-md strong {{ font-weight:650; }}
.mail-md em {{ font-style:italic; }}
.mail-md a {{ color:{t['accent_hover']};text-decoration:underline;text-underline-offset:2px; }}
.mail-md code {{
  background:{t['code_bg']};border:1px solid {t['border']};border-radius:6px;
  padding:0.1rem 0.35rem;font-size:0.86em;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
}}
.mail-md pre {{
  background:rgba(0,0,0,0.35);border:1px solid {t['border']};border-radius:10px;
  padding:0.75rem 0.9rem;overflow-x:auto;margin:0 0 0.9rem;font-size:0.85rem;line-height:1.5;
}}
.mail-md pre code {{ background:transparent;border:none;padding:0;font-size:inherit; }}
.mail-md blockquote {{
  margin:0 0 0.8rem;padding:0.35rem 0.85rem;border-left:3px solid {t['accent']};
  color:{t['muted']};background:{t['blockquote_bg']};border-radius:0 8px 8px 0;
}}
.mail-md hr {{ border:none;border-top:1px solid {t['border']};margin:1rem 0; }}
.mail-md table {{
  width:100%;border-collapse:collapse;margin:0.25rem 0 0.9rem;font-size:0.9rem;
  border:1px solid {t['border']};border-radius:10px;overflow:hidden;
}}
.mail-md thead {{ background:{t['surface_2']}; }}
.mail-md th,.mail-md td {{ border:1px solid {t['border']};padding:0.55rem 0.7rem;text-align:left;vertical-align:top; }}
.mail-md th {{ font-weight:650;color:{t['text']}; }}
.mail-md tbody tr:nth-child(even) {{ background:rgba(255,255,255,0.02); }}
@media (max-width:600px) {{
  .mail-page {{ padding:10px 8px !important; }}
  .mail-wrap {{ padding:14px 14px !important;border-radius:12px !important; }}
  .mail-body {{ padding:12px 14px !important; }}
  .mail-title {{ font-size:18px !important; }}
  .mail-md h1 {{ font-size:1.15rem !important; }}
  .mail-md h2 {{ font-size:1.05rem !important; }}
  .mail-md p,.mail-md li {{ font-size:14px !important; }}
}}
"""


def _render_html_notification(title: str, body: str, suggested_action: str | None) -> str:
    body_inner = _markdown_to_safe_html(body)
    badge = ""
    if suggested_action:
        badge = (
            "<p class='mail-badge-wrap'>"
            "<span class='mail-badge'>"
            f"Suggested action: {escape(suggested_action)}"
            "</span></p>"
        )
    # Subtle accent in header line (many clients ignore gradient on text).
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{escape(title)}</title>
<style>{_mail_styles()}</style>
</head>
<body class="mail-page">
<div class="mail-wrap">
  <h1 class="mail-title">{escape(title)}</h1>
  <p class="mail-subtitle">Portfolio-aware market notification</p>
  {badge}
  <div class="mail-body mail-md">
    {body_inner}
  </div>
</div>
</body>
</html>"""


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
