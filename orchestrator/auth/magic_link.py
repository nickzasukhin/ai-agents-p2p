"""Magic link token generation and verification using JWT.

Tokens are short-lived (15min default), single-use, and stored in the database
to prevent replay attacks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import base64
import secrets
from datetime import datetime, timezone, timedelta

import structlog

log = structlog.get_logger()


def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


class MagicLinkManager:
    """Generate and verify magic link JWT-like tokens.

    Uses HMAC-SHA256 for signing — lightweight, no external JWT library needed.
    """

    def __init__(self, secret: str, expiry_minutes: int = 15, base_url: str = ""):
        self.secret = secret.encode() if isinstance(secret, str) else secret
        self.expiry_minutes = expiry_minutes
        self.base_url = base_url.rstrip("/")

    def create_token(self, email: str) -> tuple[str, str]:
        """Create a magic link token for the given email.

        Returns:
            Tuple of (token, expires_at_iso) for storage + email.
        """
        now = time.time()
        expires_at = now + (self.expiry_minutes * 60)
        nonce = secrets.token_hex(16)

        payload = {
            "email": email.lower().strip(),
            "exp": expires_at,
            "iat": now,
            "nonce": nonce,
        }

        # Build JWT-like token: header.payload.signature
        header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "magic"}).encode())
        body = _b64url_encode(json.dumps(payload).encode())
        signature = _b64url_encode(
            hmac.new(self.secret, f"{header}.{body}".encode(), hashlib.sha256).digest()
        )

        token = f"{header}.{body}.{signature}"
        expires_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

        return token, expires_iso

    def verify_token(self, token: str) -> dict | None:
        """Verify a magic link token.

        Returns:
            Payload dict {email, exp, iat, nonce} if valid, None if invalid/expired.
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header_b64, body_b64, sig_b64 = parts

            # Verify signature
            expected_sig = _b64url_encode(
                hmac.new(
                    self.secret, f"{header_b64}.{body_b64}".encode(), hashlib.sha256
                ).digest()
            )
            if not hmac.compare_digest(sig_b64, expected_sig):
                log.warning("magic_link_bad_signature")
                return None

            # Decode payload
            payload = json.loads(_b64url_decode(body_b64))

            # Check expiry
            if time.time() > payload.get("exp", 0):
                log.info("magic_link_expired", email=payload.get("email", ""))
                return None

            return payload

        except Exception as e:
            log.warning("magic_link_verify_error", error=str(e))
            return None

    def build_link(self, token: str) -> str:
        """Build the full magic link URL."""
        return f"{self.base_url}/auth/verify?token={token}"


class SessionManager:
    """Manage session tokens (issued after magic link verification).

    Sessions are longer-lived (72h default) and used for API access.
    """

    def __init__(self, secret: str, expiry_hours: int = 72):
        self.secret = secret.encode() if isinstance(secret, str) else secret
        self.expiry_hours = expiry_hours

    def create_session(self, user_id: str, email: str) -> str:
        """Create a session token after successful magic link auth."""
        now = time.time()
        expires_at = now + (self.expiry_hours * 3600)

        payload = {
            "user_id": user_id,
            "email": email,
            "exp": expires_at,
            "iat": now,
            "type": "session",
        }

        header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "session"}).encode())
        body = _b64url_encode(json.dumps(payload).encode())
        signature = _b64url_encode(
            hmac.new(self.secret, f"{header}.{body}".encode(), hashlib.sha256).digest()
        )

        return f"{header}.{body}.{signature}"

    def verify_session(self, token: str) -> dict | None:
        """Verify a session token.

        Returns:
            Payload dict {user_id, email, exp, iat} if valid, None otherwise.
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header_b64, body_b64, sig_b64 = parts

            expected_sig = _b64url_encode(
                hmac.new(
                    self.secret, f"{header_b64}.{body_b64}".encode(), hashlib.sha256
                ).digest()
            )
            if not hmac.compare_digest(sig_b64, expected_sig):
                return None

            payload = json.loads(_b64url_decode(body_b64))

            if payload.get("type") != "session":
                return None

            if time.time() > payload.get("exp", 0):
                return None

            return payload

        except Exception:
            return None
