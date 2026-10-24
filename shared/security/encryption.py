"""AES-256-GCM encryption service with HKDF-SHA256 (v2) and PBKDF2 backward compatibility (v1).

Prompt 10 section 6.7:
- Reads MASTER_ENCRYPTION_KEY or ENCRYPTION_KEY (>= 32 bytes) from the environment.
  Non-dev environments fail fast on startup if missing or too short.
- Keeps decrypting v1: (deterministic AES-GCM, zero/static salt) for backwards compatibility.
- Encrypts as v2:{salt}:{nonce}:{tag}:{ct} (all base64). A random 16-byte salt per ciphertext
  derives a per-record key via HKDF-SHA256 with info b"antigravity-field-encryption-v2".
- Fail-secure error handling on tag mismatch or tampering.
"""
import base64
import logging
import os
from typing import Optional, Dict
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)

DEFAULT_STATIC_SALT_V1 = b"PMS_App_Static_Salt_2026!@#"
DEFAULT_SECRET_V1 = os.environ.get("SMTP_ENCRYPTION_SECRET", "PMS_Production_Secure_Encryption_Key_2026")
HKDF_INFO_V2 = b"antigravity-field-encryption-v2"


def _resolve_master_key(explicit_key: Optional[str] = None) -> bytes:
    """Resolves master encryption key, enforcing >= 32 bytes in non-dev environments."""
    raw_key = (
        explicit_key
        or os.environ.get("MASTER_ENCRYPTION_KEY")
        or os.environ.get("ENCRYPTION_KEY")
        or os.environ.get("SMTP_ENCRYPTION_SECRET")
    )
    is_dev = os.environ.get("APP_ENV", "development").lower() in ("development", "dev", "test")

    if not raw_key:
        if is_dev:
            raw_key = "PMS_Dev_Master_Encryption_Key_2026_AtLeast32BytesLong!"
        else:
            raise RuntimeError("MASTER_ENCRYPTION_KEY or ENCRYPTION_KEY environment variable is required in production.")

    key_bytes = raw_key.encode("utf-8") if isinstance(raw_key, str) else raw_key
    if len(key_bytes) < 32:
        raise ValueError(f"Master encryption key must be at least 32 bytes, got {len(key_bytes)} bytes.")

    return key_bytes


class EncryptionService:
    def __init__(
        self,
        active_key_version: str = "v2",
        keys: Optional[Dict[str, str]] = None,
        master_key: Optional[str] = None,
        v1_salt: bytes = DEFAULT_STATIC_SALT_V1,
    ):
        self._active_key_version = active_key_version
        self._v1_salt = v1_salt
        self._master_key_bytes = _resolve_master_key(master_key)

        # Legacy v1 key derivation for backward compatibility
        raw_v1 = (keys or {}).get("v1") or os.environ.get("SMTP_ENCRYPTION_SECRET_V1", DEFAULT_SECRET_V1)
        self._v1_key = self._derive_v1_key(raw_v1)

    def _derive_v1_key(self, secret: str) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._v1_salt,
            iterations=100_000,
        )
        return kdf.derive(secret.encode("utf-8"))

    def _derive_v2_key(self, salt: bytes) -> bytes:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=HKDF_INFO_V2,
        )
        return hkdf.derive(self._master_key_bytes)

    def encrypt(self, plain_text: Optional[str]) -> Optional[str]:
        if not plain_text:
            return plain_text

        try:
            plain_bytes = plain_text.encode("utf-8")
            if self._active_key_version == "v1":
                # Legacy v1 wire format
                nonce = os.urandom(12)
                aesgcm = AESGCM(self._v1_key)
                ct_with_tag = aesgcm.encrypt(nonce, plain_bytes, None)
                payload = nonce + ct_with_tag[-16:] + ct_with_tag[:-16]
                return f"v1:{base64.b64encode(payload).decode('utf-8')}"

            # Modern v2 format: v2:{salt}:{nonce}:{tag}:{ct} (all base64)
            salt = os.urandom(16)
            key = self._derive_v2_key(salt)
            nonce = os.urandom(12)
            aesgcm = AESGCM(key)

            ct_with_tag = aesgcm.encrypt(nonce, plain_bytes, None)
            ct = ct_with_tag[:-16]
            tag = ct_with_tag[-16:]

            salt_b64 = base64.b64encode(salt).decode("utf-8")
            nonce_b64 = base64.b64encode(nonce).decode("utf-8")
            tag_b64 = base64.b64encode(tag).decode("utf-8")
            ct_b64 = base64.b64encode(ct).decode("utf-8")

            return f"v2:{salt_b64}:{nonce_b64}:{tag_b64}:{ct_b64}"
        except Exception as ex:
            logger.error("[SECURITY] Encryption process failed: %s", ex, exc_info=True)
            return None

    def decrypt(self, cipher_text: Optional[str]) -> Optional[str]:
        if not cipher_text:
            return cipher_text

        try:
            if cipher_text.startswith("v2:"):
                # Handle v2
                parts = cipher_text.split(":")
                if len(parts) != 5:
                    logger.warning("[SECURITY] Decryption failed: invalid v2 format")
                    return None
                _, salt_b64, nonce_b64, tag_b64, ct_b64 = parts
                salt = base64.b64decode(salt_b64)
                nonce = base64.b64decode(nonce_b64)
                tag = base64.b64decode(tag_b64)
                ct = base64.b64decode(ct_b64)

                if len(salt) != 16 or len(nonce) != 12 or len(tag) != 16:
                    logger.warning("[SECURITY] Decryption failed: invalid v2 part lengths")
                    return None

                key = self._derive_v2_key(salt)
                aesgcm = AESGCM(key)
                plain_bytes = aesgcm.decrypt(nonce, ct + tag, None)
                return plain_bytes.decode("utf-8")

            # Handle v1 or un-prefixed legacy format
            actual_cipher_text = cipher_text
            if cipher_text.startswith("v1:"):
                actual_cipher_text = cipher_text[3:]

            full_cipher = base64.b64decode(actual_cipher_text)
            if len(full_cipher) < 28:
                logger.warning(
                    "[SECURITY] Decryption failed: Ciphertext payload is too short (%d bytes)",
                    len(full_cipher),
                )
                return None

            nonce = full_cipher[:12]
            tag = full_cipher[12:28]
            cipher_bytes = full_cipher[28:]

            aesgcm = AESGCM(self._v1_key)
            plain_bytes = aesgcm.decrypt(nonce, cipher_bytes + tag, None)
            return plain_bytes.decode("utf-8")

        except InvalidTag:
            logger.warning(
                "[SECURITY THREAT] Authentication tag mismatch. "
                "The encrypted data was tampered with or the wrong key was used."
            )
            return None
        except (ValueError, TypeError) as ex:
            logger.warning("[SECURITY] Decryption failed: Invalid base64 or payload: %s", ex)
            return None
        except Exception as ex:
            logger.error("[SECURITY] Unexpected error during decryption: %s", ex, exc_info=True)
            return None


default_encryption_service = EncryptionService()
