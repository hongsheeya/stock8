"""Encryption at rest for secret trading_config values (broker keys, tokens).

10-21, pre-launch: app keys, secrets, account numbers and access tokens were
stored as plain text, so a copied trading.db exposed every user's broker
access. Values flagged is_secret are now stored as "enc:v1:<Fernet token>".
Reads decrypt transparently (trading_config.Model.value), so the many direct
`trading.db("trading_config").get(...)` callers keep working unchanged.

The key comes from STOCK8_CONFIG_KEY (a Fernet key), else the file named by
STOCK8_CONFIG_KEY_FILE, else ~/.stock8/config.key (created on first use, kept
outside the project and its data folder). Losing the key makes stored secrets
unreadable: they read as "" and users must enter their API keys again.
"""
import base64
import os
import sys

PREFIX = "enc:v1:"
_STATE = sys.__dict__.setdefault("_stock8_secret_box", {"fernet": None, "error": ""})


def _key_file():
    path = os.environ.get("STOCK8_CONFIG_KEY_FILE", "").strip()
    if path:
        return path
    return os.path.join(os.path.expanduser("~"), ".stock8", "config.key")


def _load_key():
    env = os.environ.get("STOCK8_CONFIG_KEY", "").strip()
    if env:
        return env.encode("ascii")
    from cryptography.fernet import Fernet
    path = _key_file()
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            # O_EXCL: LIVE and PAPER may start together; only one creates it.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(Fernet.generate_key())
        except FileExistsError:
            pass
    with open(path, "rb") as handle:
        return handle.read().strip()


def _fernet():
    if _STATE["fernet"] is None:
        from cryptography.fernet import Fernet
        key = _load_key()
        base64.urlsafe_b64decode(key)  # a malformed key fails loudly here
        _STATE["fernet"] = Fernet(key)
    return _STATE["fernet"]


def is_encrypted(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value):
    value = "" if value is None else str(value)
    if value == "" or is_encrypted(value):
        return value
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value):
    if not is_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except Exception as exc:
        # Wrong or lost key: behave as "not configured" instead of handing a
        # ciphertext to the broker client.
        _STATE["error"] = type(exc).__name__
        return ""


def reset():
    """Tests: forget the loaded key."""
    _STATE["fernet"] = None
    _STATE["error"] = ""


class SecretBox:
    PREFIX = PREFIX
    encrypt = staticmethod(encrypt)
    decrypt = staticmethod(decrypt)
    is_encrypted = staticmethod(is_encrypted)
    reset = staticmethod(reset)

    @staticmethod
    def last_error():
        return _STATE["error"]


Model = SecretBox
