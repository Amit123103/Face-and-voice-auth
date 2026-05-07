"""
Encryption Service — AES-256-GCM encryption for all biometric data.
Per-user keys derived via PBKDF2-HMAC-SHA256, master key from environment.
"""

import base64
import os
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from backend.config import get_settings

settings = get_settings()

PBKDF2_ITERATIONS = 100_000
SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32


class EncryptionService:
    """Handles AES-256-GCM encryption and decryption of biometric data."""

    def __init__(self) -> None:
        self._master_key = settings.master_key_bytes
        if len(self._master_key) != KEY_SIZE:
            raise ValueError(
                f"MASTER_KEY must be exactly {KEY_SIZE} bytes when base64-decoded, "
                f"got {len(self._master_key)} bytes."
            )

    def _derive_user_key(self, user_id: str, salt: bytes) -> bytes:
        """Derive a per-user encryption key using PBKDF2-HMAC-SHA256."""
        combined_material = self._master_key + user_id.encode("utf-8")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_SIZE,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
            backend=default_backend(),
        )
        return kdf.derive(combined_material)

    def generate_salt(self) -> str:
        """Generate a random 16-byte salt, returned as base64 string."""
        return base64.b64encode(os.urandom(SALT_SIZE)).decode("utf-8")

    def encrypt(self, plaintext: bytes, user_id: str, salt_b64: str) -> Tuple[str, str]:
        """
        Encrypt plaintext bytes with AES-256-GCM.

        Returns:
            Tuple of (ciphertext_base64, nonce_base64)
        """
        salt = base64.b64decode(salt_b64)
        user_key = self._derive_user_key(user_id, salt)
        nonce = os.urandom(NONCE_SIZE)
        aesgcm = AESGCM(user_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return (
            base64.b64encode(ciphertext).decode("utf-8"),
            base64.b64encode(nonce).decode("utf-8"),
        )

    def encrypt_binary(self, plaintext: bytes, user_id: str, salt_b64: str) -> Tuple[bytes, bytes]:
        """
        Encrypt raw bytes with AES-256-GCM without Base64 overhead.
        Returns:
            Tuple of (ciphertext_bytes, nonce_bytes)
        """
        salt = base64.b64decode(salt_b64)
        user_key = self._derive_user_key(user_id, salt)
        nonce = os.urandom(NONCE_SIZE)
        aesgcm = AESGCM(user_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return ciphertext, nonce

    def decrypt_binary(self, ciphertext: bytes, nonce: bytes, user_id: str, salt_b64: str) -> bytes:
        """
        Decrypt raw bytes with AES-256-GCM.
        Returns:
            Decrypted plaintext bytes.
        """
        salt = base64.b64decode(salt_b64)
        user_key = self._derive_user_key(user_id, salt)
        aesgcm = AESGCM(user_key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    def decrypt(self, ciphertext_b64: str, nonce_b64: str, user_id: str, salt_b64: str) -> bytes:
        """
        Decrypt a base64-encoded ciphertext with AES-256-GCM.

        Returns:
            Decrypted plaintext bytes.
        """
        salt = base64.b64decode(salt_b64)
        user_key = self._derive_user_key(user_id, salt)
        nonce = base64.b64decode(nonce_b64)
        ciphertext = base64.b64decode(ciphertext_b64)
        aesgcm = AESGCM(user_key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    async def rotate_key_for_user(
        self,
        user_id: str,
        old_salt_b64: str,
        encrypted_blobs: list,
    ) -> Tuple[str, list]:
        """
        Re-encrypt all biometric blobs for a user with a new salt.
        Supports zero-downtime key rotation.

        Args:
            user_id: The user whose keys are being rotated.
            old_salt_b64: The current salt for decryption.
            encrypted_blobs: List of dicts with 'ciphertext_b64' and 'nonce_b64'.

        Returns:
            Tuple of (new_salt_b64, list of re-encrypted blobs).
        """
        new_salt_b64 = self.generate_salt()
        re_encrypted = []
        for blob in encrypted_blobs:
            plaintext = self.decrypt(
                blob["ciphertext_b64"],
                blob["nonce_b64"],
                user_id,
                old_salt_b64,
            )
            new_ct, new_nonce = self.encrypt(plaintext, user_id, new_salt_b64)
            re_encrypted.append({"ciphertext_b64": new_ct, "nonce_b64": new_nonce})
        return new_salt_b64, re_encrypted


encryption_service = EncryptionService()
