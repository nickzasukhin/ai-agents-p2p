"""DID Identity Manager — Ed25519 keypair generation, did:key format, sign/verify.

Uses PyNaCl for Ed25519 cryptographic operations.
DID format: did:key:z6Mk... (multibase base58btc Ed25519 public key)

Agent Cards are signed with a JSON-LD-style proof containing:
- type: Ed25519Signature2020
- verificationMethod: did:key:z6Mk...
- created: ISO timestamp
- proofValue: base64url-encoded signature
"""

from __future__ import annotations

import json
import base64
import hashlib
import structlog
from pathlib import Path
from datetime import datetime, timezone

from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import RawEncoder
from nacl.exceptions import BadSignatureError

log = structlog.get_logger()

# Multicodec prefix for Ed25519 public key (0xed01)
_ED25519_MULTICODEC = b"\xed\x01"

# Base58btc alphabet (Bitcoin)
_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> str:
    """Base58btc encode (used in did:key multibase)."""
    n = int.from_bytes(data, "big")
    result = []
    while n > 0:
        n, r = divmod(n, 58)
        result.append(_B58_ALPHABET[r:r + 1])
    # Preserve leading zeros
    for byte in data:
        if byte == 0:
            result.append(b"1")
        else:
            break
    return b"".join(reversed(result)).decode("ascii")


def _b58decode(s: str) -> bytes:
    """Base58btc decode."""
    n = 0
    for ch in s.encode("ascii"):
        n = n * 58 + _B58_ALPHABET.index(ch)
    # Calculate byte length
    byte_length = (n.bit_length() + 7) // 8
    result = n.to_bytes(byte_length, "big") if byte_length > 0 else b""
    # Restore leading zeros
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + result


class DIDManager:
    """Manages Ed25519 DID identity for an agent.

    Generates or loads keypair, creates did:key identifier,
    signs and verifies Agent Cards.
    """

    def __init__(self, identity_path: str | Path | None = None):
        self.identity_path = Path(identity_path) if identity_path else None
        self._signing_key: SigningKey | None = None
        self._verify_key: VerifyKey | None = None
        self._did: str = ""

    @property
    def did(self) -> str:
        return self._did

    @property
    def public_key_bytes(self) -> bytes:
        return bytes(self._verify_key) if self._verify_key else b""

    @property
    def public_key_b64(self) -> str:
        return base64.urlsafe_b64encode(self.public_key_bytes).decode() if self._verify_key else ""

    def init(self) -> str:
        """Initialize identity — load from file or generate new keypair.

        Returns the DID string.
        """
        if self.identity_path and self.identity_path.exists():
            self._load()
        else:
            self._generate()
            if self.identity_path:
                self._save()
        return self._did

    def _generate(self) -> None:
        """Generate a new Ed25519 keypair."""
        self._signing_key = SigningKey.generate()
        self._verify_key = self._signing_key.verify_key
        self._did = self._pubkey_to_did(bytes(self._verify_key))
        log.info("did_generated", did=self._did)

    def _load(self) -> None:
        """Load keypair from identity file."""
        data = json.loads(self.identity_path.read_text(encoding="utf-8"))
        seed = base64.urlsafe_b64decode(data["private_key_seed"])
        self._signing_key = SigningKey(seed)
        self._verify_key = self._signing_key.verify_key
        self._did = data["did"]
        log.info("did_loaded", did=self._did, path=str(self.identity_path))

    def _save(self) -> None:
        """Save keypair to identity file."""
        self.identity_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "did": self._did,
            "public_key": self.public_key_b64,
            "private_key_seed": base64.urlsafe_b64encode(
                bytes(self._signing_key)[:32]  # Ed25519 seed is first 32 bytes
            ).decode(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.identity_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.info("did_saved", path=str(self.identity_path))

    @staticmethod
    def _pubkey_to_did(pubkey_bytes: bytes) -> str:
        """Convert Ed25519 public key to did:key format.

        Format: did:key:z<base58btc(multicodec_prefix + public_key)>
        """
        multicodec = _ED25519_MULTICODEC + pubkey_bytes
        encoded = _b58encode(multicodec)
        return f"did:key:z{encoded}"

    @staticmethod
    def _did_to_pubkey(did: str) -> bytes:
        """Extract Ed25519 public key bytes from did:key string."""
        if not did.startswith("did:key:z"):
            raise ValueError(f"Invalid did:key format: {did}")
        encoded = did[len("did:key:z"):]
        decoded = _b58decode(encoded)
        if not decoded.startswith(_ED25519_MULTICODEC):
            raise ValueError(f"Invalid multicodec prefix in DID: {did}")
        return decoded[len(_ED25519_MULTICODEC):]

    def sign_card(self, card_dict: dict) -> dict:
        """Sign an Agent Card dict, adding a 'proof' field.

        Args:
            card_dict: Agent Card as a dict (without proof)

        Returns:
            Agent Card dict with 'proof' field added.
        """
        if not self._signing_key:
            raise RuntimeError("DID not initialized — call init() first")

        # Create canonical bytes to sign (sorted JSON without proof)
        card_copy = {k: v for k, v in card_dict.items() if k != "proof"}
        canonical = json.dumps(card_copy, sort_keys=True, separators=(",", ":")).encode("utf-8")

        # Sign
        signed = self._signing_key.sign(canonical, encoder=RawEncoder)
        signature = signed.signature

        # Add proof
        card_dict["proof"] = {
            "type": "Ed25519Signature2020",
            "verificationMethod": self._did,
            "created": datetime.now(timezone.utc).isoformat(),
            "proofValue": base64.urlsafe_b64encode(signature).decode(),
        }

        log.info("card_signed", did=self._did)
        return card_dict

    @staticmethod
    def verify_card(card_dict: dict) -> bool:
        """Verify the signature on an Agent Card.

        Args:
            card_dict: Agent Card dict with 'proof' field.

        Returns:
            True if signature is valid, False otherwise.
        """
        proof = card_dict.get("proof")
        if not proof:
            log.debug("card_no_proof")
            return False

        try:
            did = proof["verificationMethod"]
            sig_b64 = proof["proofValue"]

            # Extract public key from DID
            pubkey_bytes = DIDManager._did_to_pubkey(did)
            verify_key = VerifyKey(pubkey_bytes)

            # Reconstruct canonical message
            card_copy = {k: v for k, v in card_dict.items() if k != "proof"}
            canonical = json.dumps(card_copy, sort_keys=True, separators=(",", ":")).encode("utf-8")

            # Verify
            signature = base64.urlsafe_b64decode(sig_b64)
            verify_key.verify(canonical, signature, encoder=RawEncoder)

            log.info("card_verified", did=did)
            return True

        except (BadSignatureError, KeyError, ValueError) as e:
            log.warning("card_verification_failed", error=str(e))
            return False

    def node_id(self) -> bytes:
        """Get SHA-256 hash of the DID — used as node ID for DHT."""
        return hashlib.sha256(self._did.encode()).digest()
