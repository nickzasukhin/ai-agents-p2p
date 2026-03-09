"""Minimal DID signature verification for the registry.

Extracted from src/identity/did.py to avoid importing the full project.
"""

import json
import base64

try:
    from nacl.signing import VerifyKey
    from nacl.encoding import RawEncoder
    from nacl.exceptions import BadSignatureError

    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False

# Multicodec prefix for Ed25519 public key
_ED25519_MULTICODEC = b"\xed\x01"
_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(s: str) -> bytes:
    n = 0
    for ch in s.encode("ascii"):
        n = n * 58 + _B58_ALPHABET.index(ch)
    byte_length = (n.bit_length() + 7) // 8
    result = n.to_bytes(byte_length, "big") if byte_length > 0 else b""
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + result


def verify_card_signature(card_dict: dict) -> bool:
    """Verify an Ed25519 DID signature on an Agent Card.

    Returns True if valid, False if invalid or PyNaCl not available.
    """
    if not NACL_AVAILABLE:
        return False

    proof = card_dict.get("proof")
    if not proof:
        return False

    try:
        did = proof["verificationMethod"]
        sig_b64 = proof["proofValue"]

        # Extract public key from did:key
        if not did.startswith("did:key:z"):
            return False
        encoded = did[len("did:key:z"):]
        decoded = _b58decode(encoded)
        if not decoded.startswith(_ED25519_MULTICODEC):
            return False
        pubkey_bytes = decoded[len(_ED25519_MULTICODEC):]

        verify_key = VerifyKey(pubkey_bytes)

        # Reconstruct canonical message
        card_copy = {k: v for k, v in card_dict.items() if k != "proof"}
        canonical = json.dumps(card_copy, sort_keys=True, separators=(",", ":")).encode("utf-8")

        signature = base64.urlsafe_b64decode(sig_b64)
        verify_key.verify(canonical, signature, encoder=RawEncoder)
        return True

    except (BadSignatureError, KeyError, ValueError, Exception):
        return False
