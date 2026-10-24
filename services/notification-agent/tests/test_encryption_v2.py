import os
import pytest
from shared.security.encryption import EncryptionService


def test_v2_roundtrip():
    svc = EncryptionService(master_key="a" * 32)
    plaintext = "super-secret-password-123"
    cipher = svc.encrypt(plaintext)
    assert cipher.startswith("v2:")
    decrypted = svc.decrypt(cipher)
    assert decrypted == plaintext


def test_v1_backward_compatibility():
    # Service with v1 active encrypts in v1 format
    svc_v1 = EncryptionService(active_key_version="v1", master_key="a" * 32)
    plaintext = "v1-legacy-secret"
    cipher_v1 = svc_v1.encrypt(plaintext)
    assert cipher_v1.startswith("v1:")

    # Service with default v2 can decrypt v1
    svc_v2 = EncryptionService(active_key_version="v2", master_key="a" * 32)
    decrypted = svc_v2.decrypt(cipher_v1)
    assert decrypted == plaintext


def test_different_ciphertexts_for_same_plaintext():
    svc = EncryptionService(master_key="a" * 32)
    plaintext = "identical-plaintext"
    c1 = svc.encrypt(plaintext)
    c2 = svc.encrypt(plaintext)
    assert c1 != c2
    assert svc.decrypt(c1) == plaintext
    assert svc.decrypt(c2) == plaintext


def test_tamper_resistance():
    svc = EncryptionService(master_key="a" * 32)
    plaintext = "do-not-tamper-with-me"
    cipher = svc.encrypt(plaintext)
    parts = cipher.split(":")
    # Tamper with the ciphertext component
    tampered_ct = parts[4][:-4] + "AAAA"
    tampered_cipher = ":".join(parts[:4] + [tampered_ct])
    decrypted = svc.decrypt(tampered_cipher)
    assert decrypted is None


def test_invalid_key_length():
    with pytest.raises(ValueError, match="at least 32 bytes"):
        EncryptionService(master_key="too-short-key")
