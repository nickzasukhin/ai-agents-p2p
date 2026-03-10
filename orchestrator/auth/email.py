"""Email sending for magic link authentication.

Supports:
  - Resend (primary, recommended)
  - SMTP fallback (for self-hosted)
  - Console/log mode (development)
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


class EmailSender:
    """Send magic link emails."""

    def __init__(
        self,
        resend_api_key: str = "",
        email_from: str = "noreply@devpunks.io",
        enabled: bool = True,
    ):
        self.resend_api_key = resend_api_key
        self.email_from = email_from
        self.enabled = enabled

    async def send_magic_link(self, to_email: str, magic_link: str, agent_name: str = "") -> bool:
        """Send magic link email.

        Args:
            to_email: Recipient email address.
            magic_link: Full URL of the magic link.
            agent_name: Optional agent name for personalization.

        Returns:
            True if sent successfully, False otherwise.
        """
        subject = "Sign in to DevPunks Agents"
        html = self._build_email_html(magic_link, agent_name)

        if not self.enabled:
            log.info("email_disabled_log_only", to=to_email, link=magic_link)
            return True

        if self.resend_api_key:
            return await self._send_via_resend(to_email, subject, html)

        # Fallback: log to console (development mode)
        log.info("email_no_provider_log", to=to_email, link=magic_link)
        return True

    async def _send_via_resend(self, to: str, subject: str, html: str) -> bool:
        """Send email via Resend API."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self.resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": self.email_from,
                        "to": [to],
                        "subject": subject,
                        "html": html,
                    },
                )
                if resp.status_code in (200, 201):
                    log.info("email_sent_resend", to=to)
                    return True
                else:
                    log.error("email_resend_error", status=resp.status_code, body=resp.text[:200])
                    return False
        except Exception as e:
            log.error("email_send_error", error=str(e))
            return False

    def _build_email_html(self, magic_link: str, agent_name: str = "") -> str:
        """Build the HTML email body with DevPunks branding."""
        title = f"Sign in to {agent_name}" if agent_name else "Sign in to DevPunks Agents"
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0; padding:0; background:#0a0a0f; font-family:Inter,system-ui,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f; padding:40px 0;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0" style="background:#12121a; border-radius:12px; padding:40px;">
        <tr><td align="center" style="padding-bottom:24px;">
          <h1 style="color:#FFFFFF; font-size:24px; margin:0;">
            Dev<span style="color:#E50051;">/</span>Punks
          </h1>
          <p style="color:#8888aa; font-size:14px; margin:8px 0 0;">AI Agent Network</p>
        </td></tr>
        <tr><td style="padding:0 0 24px;">
          <h2 style="color:#FFFFFF; font-size:18px; margin:0 0 12px;">{title}</h2>
          <p style="color:#8888aa; font-size:14px; line-height:1.6; margin:0;">
            Click the button below to sign in. This link expires in 15 minutes.
          </p>
        </td></tr>
        <tr><td align="center" style="padding:0 0 24px;">
          <a href="{magic_link}"
             style="display:inline-block; background:#E50051; color:#FFFFFF; text-decoration:none;
                    padding:14px 32px; border-radius:8px; font-size:16px; font-weight:600;">
            Sign In
          </a>
        </td></tr>
        <tr><td style="border-top:1px solid #1a1a2e; padding-top:16px;">
          <p style="color:#555570; font-size:12px; margin:0; line-height:1.5;">
            If you didn't request this, you can safely ignore this email.<br>
            <a href="{magic_link}" style="color:#555570; word-break:break-all;">{magic_link}</a>
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
