"""External notification fan-out adapters for Cygnus.

Ownership:
- email/webhook delivery adapters live here as outward integration surfaces
- the in-app inbox remains the source of truth under ``cygnus.runtime.services.notification_service``
- this module is an external delivery adapter, not the governance domain itself
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

from cygnus.runtime.database.models import Employee, Notification
from cygnus.runtime.services.config_service import ConfigService


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


async def _dispatch_email_batch(
    db: AsyncSession,
    cfg: ConfigService,
    notifications: list[Notification],
) -> None:
    try:
        host = await cfg.get("smtp_host")
        if not host:
            logger.warning("SMTP enabled but smtp_host not configured")
            return
        port = int(await cfg.get("smtp_port") or "587")
        username = await cfg.get("smtp_username")
        password = await cfg.get("smtp_password")
        from_addr = await cfg.get("smtp_from") or "cygnus@localhost"
        use_tls = (await cfg.get("smtp_use_tls") or "true").lower() == "true"
    except Exception as exc:
        logger.warning(f"SMTP config load failed: {exc}")
        return

    by_recipient: dict[uuid.UUID, list[Notification]] = {}
    for notification in notifications:
        by_recipient.setdefault(notification.recipient_id, []).append(notification)

    for recipient_id, items in by_recipient.items():
        employee = await db.get(Employee, recipient_id)
        if not employee or not employee.email:
            continue
        subject = items[0].subject if len(items) == 1 else f"Cygnus — {len(items)} new notifications"
        body = _build_email_body(employee.name or employee.email, items)
        try:
            await _send_smtp(
                host=host,
                port=port,
                username=username,
                password=password,
                from_addr=from_addr,
                to_addr=employee.email,
                subject=subject,
                body=body,
                use_tls=use_tls,
            )
        except Exception as exc:
            logger.warning(f"SMTP send failed for {employee.email}: {exc}")


def _build_email_body(name: str, items: list[Notification]) -> str:
    lines = [f"Hi {name},", ""]
    if len(items) == 1:
        notification = items[0]
        lines.append(notification.subject)
        lines.append("")
        if notification.body:
            lines.append(notification.body)
            lines.append("")
    else:
        lines.append("You have new activity on Cygnus:")
        lines.append("")
        for notification in items:
            lines.append(f"- {notification.subject}")
            if notification.body:
                lines.append(f"  {notification.body}")
        lines.append("")
    lines.append("Open Cygnus to review.")
    return "\n".join(lines)


async def _send_smtp(
    *,
    host: str,
    port: int,
    username: Optional[str],
    password: Optional[str],
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    use_tls: bool,
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


async def _dispatch_webhook_batch(
    db: AsyncSession,
    cfg: ConfigService,
    notifications: list[Notification],
) -> None:
    try:
        url = await cfg.get("webhook_url")
        if not url:
            logger.warning("Webhook enabled but webhook_url not configured")
            return
        secret = await cfg.get("webhook_secret")
    except Exception as exc:
        logger.warning(f"Webhook config load failed: {exc}")
        return

    payload = {
        "events": [
            {
                "id": str(notification.id),
                "type": notification.type,
                "subject": notification.subject,
                "body": notification.body or "",
                "target_type": notification.target_type,
                "target_id": notification.target_id,
                "recipient_id": str(notification.recipient_id),
                "actor_id": str(notification.actor_id) if notification.actor_id else None,
                "created_at": notification.created_at.isoformat() if notification.created_at else None,
            }
            for notification in notifications
        ],
    }
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "Cygnus-Webhook/1"}
    if secret:
        signature = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        headers["X-Cygnus-Signature"] = f"sha256={signature}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, content=body_bytes, headers=headers)
            if response.status_code >= 400:
                logger.warning(f"Webhook POST {url} returned {response.status_code}: {response.text[:200]}")
    except Exception as exc:
        logger.warning(f"Webhook POST {url} failed: {exc}")
