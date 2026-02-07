from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken


def _derive_key(master_key: str) -> bytes:
    digest = hashlib.sha256(master_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_json(master_key: str | None, payload: Dict[str, Any]) -> str:
    """Encrypt payload with Fernet when master_key is available.
    Returns a string token; plaintext is marked as insecure.
    """
    if not master_key:
        return json.dumps({"insecure": True, "data": payload})
    f = Fernet(_derive_key(master_key))
    token = f.encrypt(json.dumps(payload or {}).encode("utf-8")).decode("utf-8")
    return f"fernet:{token}"


def decrypt_json(master_key: str | None, token: str) -> Dict[str, Any]:
    if token is None:
        return {}
    s = str(token)
    if s.startswith("fernet:"):
        if not master_key:
            raise ValueError("master_key_missing")
        raw = s[len("fernet:") :]
        f = Fernet(_derive_key(master_key))
        try:
            data = f.decrypt(raw.encode("utf-8")).decode("utf-8")
            obj = json.loads(data)
            return obj if isinstance(obj, dict) else {}
        except InvalidToken as e:
            raise ValueError("invalid_token") from e
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "data" in obj and obj.get("insecure"):
            return obj.get("data") or {}
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
