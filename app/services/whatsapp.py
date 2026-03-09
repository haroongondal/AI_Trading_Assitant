"""
Send notifications via Meta WhatsApp Cloud API (trial/production). No-op if credentials not set.
"""
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
GRAPH_URL = "https://graph.facebook.com/v21.0"


def send_notification(title: str, body: str, suggested_action: str | None = None) -> bool:
    """Send a notification to the configured WhatsApp recipient. Returns True if sent, False if skipped or failed."""
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID or not settings.WHATSAPP_RECIPIENT_PHONE:
        return False
    text = f"{title}\n\n{body}"
    if suggested_action:
        text += f"\n\nSuggested: {suggested_action}"
    # Business-initiated messages require an approved template. Use hello_world for trial or a custom template with one body param.
    template_name = settings.WHATSAPP_TEMPLATE_NAME or "hello_world"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": settings.WHATSAPP_RECIPIENT_PHONE.replace("+", "").strip(),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en_US"},
        },
    }
    # If template has body parameters (e.g. custom template with {{1}}), pass the notification text.
    if template_name != "hello_world":
        payload["template"]["components"] = [{"type": "body", "parameters": [{"type": "text", "text": text[:1000]}]}]
    url = f"{GRAPH_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                url,
                headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"},
                json=payload,
            )
            if r.is_success:
                logger.info("WhatsApp notification sent")
                return True
            logger.warning("WhatsApp send failed: %s %s", r.status_code, r.text)
            return False
    except Exception as e:
        logger.exception("WhatsApp error: %s", e)
        return False
