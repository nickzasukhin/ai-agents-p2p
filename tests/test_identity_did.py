"""Tests for DIDManager — Ed25519 keypair, DID encoding, signing, verification."""

import json
import pytest
from pathlib import Path
from src.identity.did import DIDManager


class TestDIDGeneration:
    def test_generate_creates_valid_did(self, did_manager):
        assert did_manager.did.startswith("did:key:z")

    def test_did_format_starts_with_prefix(self, did_manager):
        assert did_manager.did.startswith("did:key:z6Mk")

    def test_public_key_bytes_length(self, did_manager):
        assert len(did_manager.public_key_bytes) == 32

    def test_public_key_b64_not_empty(self, did_manager):
        assert len(did_manager.public_key_b64) > 0

    def test_node_id_is_32_bytes(self, did_manager):
        nid = did_manager.node_id()
        assert len(nid) == 32

    def test_node_id_deterministic(self, did_manager):
        assert did_manager.node_id() == did_manager.node_id()


class TestDIDPersistence:
    def test_save_and_load_keypair(self, tmp_path):
        identity_path = tmp_path / "identity.json"
        mgr1 = DIDManager(identity_path=identity_path)
        did1 = mgr1.init()

        mgr2 = DIDManager(identity_path=identity_path)
        did2 = mgr2.init()

        assert did1 == did2
        assert mgr1.public_key_b64 == mgr2.public_key_b64

    def test_identity_file_created(self, tmp_path):
        identity_path = tmp_path / "identity.json"
        mgr = DIDManager(identity_path=identity_path)
        mgr.init()
        assert identity_path.exists()

        data = json.loads(identity_path.read_text())
        assert "did" in data
        assert "private_key_seed" in data

    def test_in_memory_no_file(self):
        mgr = DIDManager()
        did = mgr.init()
        assert did.startswith("did:key:z")


class TestDIDSigning:
    def test_sign_card_adds_proof_field(self, did_manager, sample_agent_card_dict):
        signed = did_manager.sign_card(sample_agent_card_dict)
        assert "proof" in signed
        proof = signed["proof"]
        assert proof["type"] == "Ed25519Signature2020"
        assert proof["verificationMethod"] == did_manager.did
        assert "proofValue" in proof
        assert "created" in proof

    def test_verify_card_valid_signature(self, did_manager, sample_agent_card_dict):
        signed = did_manager.sign_card(sample_agent_card_dict)
        assert DIDManager.verify_card(signed) is True

    def test_verify_card_tampered_data(self, did_manager, sample_agent_card_dict):
        signed = did_manager.sign_card(sample_agent_card_dict)
        signed["name"] = "TAMPERED"
        assert DIDManager.verify_card(signed) is False

    def test_verify_card_missing_proof(self):
        assert DIDManager.verify_card({"name": "test"}) is False

    def test_cross_manager_verification(self, tmp_path, sample_agent_card_dict):
        """Card signed by one manager can be verified by static method."""
        mgr = DIDManager(identity_path=tmp_path / "id.json")
        mgr.init()
        signed = mgr.sign_card(sample_agent_card_dict)
        assert DIDManager.verify_card(signed) is True
