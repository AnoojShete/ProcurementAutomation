"""AES-256-GCM encryption service with PBKDF2 key derivation.

Ported from C# projectmanagement.Services.EncryptionService with 100% format
and cipher compatibility:
- Key derivation: PBKDF2 with SHA256, 100,000 iterations, 32-byte key.
- Salt: static default b"PMS_App_Static_Salt_2026!@#" (or env override).
- Encryption: AES-256-GCM, 12-byte random nonce, 16-byte authentication tag.
- Wire format: {version}:{base64(nonce[12] + tag[16] + ciphertext)}.
- Fail-secure error handling on tag mismatch or tampering.
"""
import base64
import logging
import os
from typing import Optional, Dict
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)

DEFAULT_STATIC_SALT = b"PMS_App_Static_Salt_2026!@#"
DEFAULT_SECRET = os.environ.get("SMTP_ENCRYPTION_SECRET", "PMS_Production_Secure_Encryption_Key_2026")


class EncryptionService:
    def __init__(
        self,
        active_key_version: str = "v1",
        keys: Optional[Dict[str, str]] = None,
        salt: bytes = DEFAULT_STATIC_SALT,
    ):
        self._active_key_version = active_key_version
        self._salt = salt
        self._keys: Dict[str, bytes] = {}

        raw_keys = keys or {
            "v1": os.environ.get("SMTP_ENCRYPTION_SECRET_V1", DEFAULT_SECRET)
        }
        for ver, secret in raw_keys.items():
            if secret:
                self._keys[ver] = self._derive_key(secret)

        if self._active_key_version not in self._keys:
            # Fallback self-register default if missing
            self._keys[self._active_key_version] = self._derive_key(DEFAULT_SECRET)

    def _derive_key(self, secret: str) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._salt,
            iterations=100_000,
        )
        return kdf.derive(secret.encode("utf-8"))

    def encrypt(self, plain_text: Optional[str]) -> Optional[str]:
        if not plain_text:
            return plain_text

        try:
            plain_bytes = plain_text.encode("utf-8")
            nonce = os.urandom(12)
            key_to_use = self._keys[self._active_key_version]
            aesgcm = AESGCM(key_to_use)

            # In cryptography, encrypt returns ciphertext + 16-byte tag
            ct_with_tag = aesgcm.encrypt(nonce, plain_bytes, None)
            cipher_bytes = ct_with_tag[:-16]
            tag = ct_with_tag[-16:]

            # Pack: nonce (12) + tag (16) + cipher_bytes
            payload = nonce + tag + cipher_bytes
            base64_result = base64.b64encode(payload).decode("utf-8")
            return f"{self._active_key_version}:{base64_result}"
        except Exception as ex:
            logger.error("[SECURITY] Encryption process failed: %s", ex, exc_info=True)
            return None

    def decrypt(self, cipher_text: Optional[str]) -> Optional[str]:
        if not cipher_text:
            return cipher_text

        try:
            key_version = "v1"
            actual_cipher_text = cipher_text

            colon_index = cipher_text.find(":")
            if 0 < colon_index < 10:
                key_version = cipher_text[:colon_index]
                actual_cipher_text = cipher_text[colon_index + 1 :]

            key_to_use = self._keys.get(key_version)
            if not key_to_use:
                logger.error("[SECURITY] Decryption failed: Unknown key version '%s'", key_version)
                return None

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

            aesgcm = AESGCM(key_to_use)
            # In cryptography, decrypt expects ciphertext + tag
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
