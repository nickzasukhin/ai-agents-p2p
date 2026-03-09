"""Privacy Guard — filters PII and sensitive data from outgoing agent messages."""

import re
import structlog

log = structlog.get_logger()

# Patterns that should be redacted from outgoing messages
PII_PATTERNS = [
    (r'\b[\w.-]+@[\w.-]+\.\w+\b', '[EMAIL_REDACTED]'),                    # Email
    (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE_REDACTED]'),               # Phone
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP_REDACTED]'),        # IP address
    (r'\b(?:sk-|pk-|api[_-]?key)[a-zA-Z0-9_-]{10,}\b', '[API_KEY_REDACTED]'),  # API keys
    (r'/(?:Users|home)/\w+/[^\s]+', '[PATH_REDACTED]'),                    # File paths
    (r'\b(?:password|passwd|pwd)\s*[=:]\s*\S+', '[PASSWORD_REDACTED]'),    # Passwords
    (r'\b[A-Za-z0-9+/]{40,}={0,2}\b', '[TOKEN_REDACTED]'),                # Long tokens/secrets
]

# Words that should trigger a warning (not auto-redact, but log)
SENSITIVE_KEYWORDS = [
    "secret", "credential", "token", "private_key", "ssh",
    ".env", "config.yaml", "database_url", "connection_string",
]

# Context sanitization — things to strip from raw context before sending to LLM
CONTEXT_STRIP_PATTERNS = [
    (r'(?i)(?:api[_-]?key|password|secret|token)\s*[=:]\s*\S+', '[REDACTED]'),
    (r'/(?:Users|home)/\w+/', '/~/'),  # Normalize home paths
]


class PrivacyGuard:
    """Filters sensitive information from agent communications.

    Applied to:
    1. Outgoing negotiation messages (filter_output)
    2. Context sent to LLM for summarization (sanitize_context)
    3. Agent Card descriptions (filter_output)
    """

    def __init__(
        self,
        extra_patterns: list[tuple[str, str]] | None = None,
        strict_mode: bool = False,
    ):
        self.patterns = PII_PATTERNS + (extra_patterns or [])
        self.strict_mode = strict_mode
        self._redaction_count = 0

    def filter_output(self, text: str) -> str:
        """Filter PII and sensitive data from outgoing text.

        Args:
            text: Text to filter (negotiation message, card description, etc.)

        Returns:
            Filtered text with PII replaced by placeholders.
        """
        filtered = text
        for pattern, replacement in self.patterns:
            matches = re.findall(pattern, filtered)
            if matches:
                self._redaction_count += len(matches)
                log.warning(
                    "pii_redacted",
                    pattern_type=replacement,
                    count=len(matches),
                )
                filtered = re.sub(pattern, replacement, filtered)

        # Check for sensitive keywords
        for keyword in SENSITIVE_KEYWORDS:
            if keyword.lower() in filtered.lower():
                log.warning("sensitive_keyword_detected", keyword=keyword)
                if self.strict_mode:
                    filtered = re.sub(
                        re.escape(keyword), "[REDACTED]", filtered, flags=re.IGNORECASE
                    )

        return filtered

    def sanitize_context(self, raw_context: str) -> str:
        """Sanitize raw owner context before sending to LLM.

        Removes file paths, credentials, and other sensitive data
        while preserving the useful content for summarization.
        """
        sanitized = raw_context
        for pattern, replacement in CONTEXT_STRIP_PATTERNS:
            sanitized = re.sub(pattern, replacement, sanitized)
        return sanitized

    def check_injection(self, incoming_text: str) -> dict:
        """Check incoming A2A messages for prompt injection attempts.

        Returns:
            dict with 'safe' (bool) and 'warnings' (list of detected issues).
        """
        warnings = []

        injection_patterns = [
            (r'(?i)ignore\s+(?:all\s+)?(?:previous|above)\s+instructions', "instruction override attempt"),
            (r'(?i)you\s+are\s+now\s+(?:a|an|acting\s+as)', "role hijacking attempt"),
            (r'(?i)(?:system|admin)\s*(?:prompt|message|override)', "system prompt injection"),
            (r'(?i)reveal\s+(?:your|the)\s+(?:system|secret|internal|prompt)', "information extraction attempt"),
            (r'(?i)(?:output|print|show|display)\s+(?:all|your)\s+(?:instructions|rules|config)', "config extraction"),
            (r'\{\{.*\}\}', "template injection"),
            (r'<\|.*\|>', "special token injection"),
        ]

        for pattern, description in injection_patterns:
            if re.search(pattern, incoming_text):
                warnings.append(description)
                log.warning("injection_detected", type=description)

        return {
            "safe": len(warnings) == 0,
            "warnings": warnings,
        }

    @property
    def stats(self) -> dict:
        return {
            "total_redactions": self._redaction_count,
            "patterns_active": len(self.patterns),
            "strict_mode": self.strict_mode,
        }
