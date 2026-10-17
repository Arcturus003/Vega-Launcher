from __future__ import annotations

import base64
import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

# DPAPI Windows native protection
_DPAPI_AVAILABLE = False
if os.name == "nt":
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        _CryptProtectData = ctypes.windll.crypt32.CryptProtectData
        _CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
        _LocalFree = ctypes.windll.kernel32.LocalFree
        _DPAPI_AVAILABLE = True
    except Exception:
        _DPAPI_AVAILABLE = False


@dataclass(frozen=True)
class AuthSession:
    username: str
    uuid: str
    access_token: str
    account_type: str = "msa"  # "msa", "ely", "offline"
    is_offline: bool = False
    raw_data: dict = None


class AuthenticationVault:
    """
    Deep module encapsulating credential encryption (Windows DPAPI),
    fast offline connectivity probing, and token preparation for game launch.
    Hides cryptographic blobs and HTTP timeout resilience behind clean entry points.
    """

    DPAPI_PREFIX = "dpapi:"

    @classmethod
    def is_network_available(cls, host: str = "1.1.1.1", port: int = 53, timeout: float = 1.2) -> bool:
        """Fast non-blocking connectivity check via DNS socket to avoid HTTP timeout lags when offline."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            return False

    @classmethod
    def needs_rebind(cls, data: str) -> bool:
        """Returns True if token is plaintext, contains a legacy portable suffix, or its DPAPI layer cannot be decrypted."""
        if not data or not isinstance(data, str):
            return False
        if not data.startswith(cls.DPAPI_PREFIX):
            return True
        b64_part, sep, _ = data[len(cls.DPAPI_PREFIX):].partition(".")
        if sep:
            return True
        if _DPAPI_AVAILABLE and not cls.decrypt_secret(data):
            return True
        return False

    @classmethod
    def encrypt_secret(cls, secret_text: str) -> str:
        """Encrypt a secret string using Windows DPAPI (tied to current Windows user login)."""
        if not secret_text:
            return ""
        if secret_text.startswith(cls.DPAPI_PREFIX):
            b64_part, sep, _ = secret_text[len(cls.DPAPI_PREFIX):].partition(".")
            if not sep and (not _DPAPI_AVAILABLE or cls.decrypt_secret(secret_text) != ""):
                return secret_text
            decrypted = cls.decrypt_secret(secret_text)
            if not decrypted:
                return f"{cls.DPAPI_PREFIX}{b64_part}" if b64_part else ""
            secret_text = decrypted

        if not _DPAPI_AVAILABLE:
            return f"{cls.DPAPI_PREFIX}{base64.b64encode(secret_text.encode('utf-8')).decode('ascii')}"

        try:
            raw_bytes = secret_text.encode("utf-8")
            blob_in = DATA_BLOB(len(raw_bytes), ctypes.cast(ctypes.create_string_buffer(raw_bytes), ctypes.POINTER(ctypes.c_byte)))
            blob_out = DATA_BLOB()

            if _CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
                try:
                    encrypted_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                    b64 = base64.b64encode(encrypted_bytes).decode("ascii")
                    return f"{cls.DPAPI_PREFIX}{b64}"
                finally:
                    _LocalFree(blob_out.pbData)
        except Exception:
            pass

        return secret_text

    @classmethod
    def decrypt_secret(cls, cipher_text: str) -> str:
        """Decrypt a DPAPI-encrypted string back to plaintext."""
        if not cipher_text:
            return ""
        if not cipher_text.startswith(cls.DPAPI_PREFIX):
            return cipher_text

        b64_part, _, _ = cipher_text[len(cls.DPAPI_PREFIX):].partition(".")
        if not _DPAPI_AVAILABLE:
            try:
                return base64.b64decode(b64_part).decode("utf-8")
            except Exception:
                return ""

        try:
            encrypted_bytes = base64.b64decode(b64_part)
            blob_in = DATA_BLOB(len(encrypted_bytes), ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_byte)))
            blob_out = DATA_BLOB()

            if _CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
                try:
                    decrypted_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                    return decrypted_bytes.decode("utf-8", errors="replace")
                finally:
                    _LocalFree(blob_out.pbData)
        except Exception:
            pass

        return ""

    @classmethod
    def protect_account_for_storage(cls, account_data: Optional[dict]) -> Optional[dict]:
        """Return a copy of account dict with sensitive tokens encrypted via DPAPI."""
        if not account_data or not isinstance(account_data, dict):
            return account_data

        copied = dict(account_data)
        for key in ("access_token", "refresh_token"):
            if copied.get(key):
                copied[key] = cls.encrypt_secret(str(copied[key]))
        return copied

    @classmethod
    def unprotect_account_for_runtime(cls, account_data: Optional[dict]) -> Optional[dict]:
        """Return a copy of account dict with DPAPI tokens decrypted for runtime use."""
        if not account_data or not isinstance(account_data, dict):
            return account_data

        copied = dict(account_data)
        for key in ("access_token", "refresh_token"):
            if copied.get(key):
                copied[key] = cls.decrypt_secret(str(copied[key]))
        return copied

    @classmethod
    def build_auth_session(cls, account_data: Optional[dict], offline_name: str = "Player") -> AuthSession:
        """Create an AuthSession instance, decrypting tokens if necessary."""
        if not account_data:
            return AuthSession(
                username=offline_name,
                uuid="",
                access_token="",
                account_type="offline",
                is_offline=True,
                raw_data={},
            )

        decrypted = cls.unprotect_account_for_runtime(account_data)
        username = decrypted.get("name") or decrypted.get("username") or offline_name
        uuid_val = decrypted.get("id") or decrypted.get("uuid") or ""
        token = decrypted.get("access_token") or decrypted.get("token") or ""
        account_type = decrypted.get("type", "msa")

        return AuthSession(
            username=username,
            uuid=uuid_val,
            access_token=token,
            account_type=account_type,
            is_offline=not bool(token),
            raw_data=decrypted,
        )


DEFAULT_AUTH_VAULT = AuthenticationVault()
