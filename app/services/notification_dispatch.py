"""
Notification dispatch — fan out a Notification row to optional external channels.

Channels are best-effort: any failure is logged and swallowed so the
contribution flow never breaks. The in-app inbox is the source of truth; email
and webhook are convenience deliveries on top.

Configuration keys (read via ConfigService):

  smtp_enabled           -> "true" / "false"  (default "false")
  smtp_host              -> string
  smtp_port              -> int (default 587)
  smtp_username          -> string
  smtp_password          -> string (encrypted via ConfigService sensitive layer)
  smtp_from              -> string e.g. "Arkon <noreply@arkon.example>"
  smtp_use_tls           -> "true" / "false" (default "true")

  webhook_enabled        -> "true" / "false"
  webhook_url            -> string (single endpoint; multi-URL is a future ext)
  webhook_secret         -> optional HMAC secret (sent in X-Arkon-Signature)

Each dispatch runs after the DB commit so we never email about something we
then roll back. Caller hands us the persisted Notification(s).
"""

import asyncio
import hashlib
import hmac
import json
import uuid
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Employee, Notification
from app.services.config_service import ConfigService


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def dispatch_external(db: AsyncSession, notifications: list[Notification]) -> None:
    """Send each notification through configured external channels.

    Runs sequentially per channel; channels run concurrently. Each channel
    catches its own exceptions and logs them.
    """
    if not notifications:
        return

    cfg = ConfigService(db)
    tasks: list[asyncio.Task] = []

    if (await cfg.get("smtp_enabled") or "false").lower() == "true":
        tasks.append(asyncio.create_task(_dispatch_email_batch(db, cfg, notifications)))
    if (await cfg.get("webhook_enabled") or "false").lower() == "true":
        tasks.append(asyncio.create_task(_dispatch_webhook_batch(db, cfg, notifications)))

    if not tasks:
        return
    await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Email channel
# ---------------------------------------------------------------------------

async def _dispatch_email_batch(
    db: AsyncSession, cfg: ConfigService, notifications: list[Notification],
) -> None:
    try:
        host = await cfg.get("smtp_host")
        if not host:
            logger.warning("SMTP enabled but smtp_host not configured")
            return
        port = int(await cfg.get("smtp_port") or "587")
        username = await cfg.get("smtp_username")
        password = await cfg.get("smtp_password")
        from_addr = await cfg.get("smtp_from") or "arkon@localhost"
        use_tls = (await cfg.get("smtp_use_tls") or "true").lower() == "true"
    except Exception as e:
        logger.warning(f"SMTP config load failed: {e}")
        return

    # Group by recipient to send one email per user covering all notifications.
    by_recipient: dict[uuid.UUID, list[Notification]] = {}
    for n in notifications:
        by_recipient.setdefault(n.recipient_id, []).append(n)

    for recipient_id, items in by_recipient.items():
        emp = await db.get(Employee, recipient_id)
        if not emp or not emp.email:
            continue
        subject = (
            items[0].subject if len(items) == 1
            else f"Arkon — {len(items)} new notifications"
        )
        body = _build_email_body(emp.name or emp.email, items)
        try:
            await _send_smtp(
                host=host, port=port, username=username, password=password,
                from_addr=from_addr, to_addr=emp.email,
                subject=subject, body=body, use_tls=use_tls,
            )
        except Exception as e:
            logger.warning(f"SMTP send failed for {emp.email}: {e}")


def _build_email_body(name: str, items: list[Notification]) -> str:
    lines = [f"Hi {name},", ""]
    if len(items) == 1:
        n = items[0]
        lines.append(n.subject)
        lines.append("")
        if n.body:
            lines.append(n.body)
            lines.append("")
    else:
        lines.append("You have new activity on Arkon:")
        lines.append("")
        for n in items:
            lines.append(f"- {n.subject}")
            if n.body:
                lines.append(f"  {n.body}")
        lines.append("")
    lines.append("Open Arkon to review.")
    return "\n".join(lines)


async def _send_smtp(
    *, host: str, port: int, username: Optional[str], password: Optional[str],
    from_addr: str, to_addr: str, subject: str, body: str, use_tls: bool,
) -> None:
    """Send a plain-text email via aiosmtplib."""
    import aiosmtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=host,
        port=port,
        username=username or None,
        password=password or None,
        start_tls=use_tls,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Webhook channel
# ---------------------------------------------------------------------------

async def _dispatch_webhook_batch(
    db: AsyncSession, cfg: ConfigService, notifications: list[Notification],
) -> None:
    try:
        url = await cfg.get("webhook_url")
        if not url:
            logger.warning("Webhook enabled but webhook_url not configured")
            return
        secret = await cfg.get("webhook_secret")
    except Exception as e:
        logger.warning(f"Webhook config load failed: {e}")
        return

    payload = {
        "events": [
            {
                "id": str(n.id),
                "type": n.type,
                "subject": n.subject,
                "body": n.body or "",
                "target_type": n.target_type,
                "target_id": n.target_id,
                "recipient_id": str(n.recipient_id),
                "actor_id": str(n.actor_id) if n.actor_id else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
    }
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "Arkon-Webhook/1"}
    if secret:
        sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        headers["X-Arkon-Signature"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, content=body_bytes, headers=headers)
            if resp.status_code >= 400:
                logger.warning(f"Webhook POST {url} returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Webhook POST {url} failed: {e}")
