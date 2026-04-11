import base64
import hashlib
import hmac
import json
import math
import os
import re
import time
from urllib.parse import parse_qsl

TOKEN = os.getenv("TOKEN", "")
ALLOWED_CHAT_IDS = [s.strip() for s in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if s.strip()]


def validate_init_data(init_data: str) -> bool:
    if not init_data:
        return False
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_val = params.pop("hash", None)
    if not hash_val:
        return False

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    # secret_key = HMAC-SHA256(key="WebAppData", msg=TOKEN)
    secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if expected != hash_val:
        return False

    try:
        user = json.loads(params.get("user", "{}"))
        if str(user.get("id", "")) not in ALLOWED_CHAT_IDS:
            return False
    except (json.JSONDecodeError, KeyError):
        return False

    return True


def _raw_token(window: int) -> str:
    raw = hmac.new(TOKEN.encode(), str(window).encode(), hashlib.sha256).digest()
    b64 = base64.b64encode(raw).decode()
    return re.sub(r"[+/=]", "", b64)[:20]


def generate_token() -> str:
    window = math.floor(time.time() / 3600)
    return _raw_token(window)


def validate_token(token: str) -> bool:
    if not token:
        return False
    window = math.floor(time.time() / 3600)
    return token in (_raw_token(window), _raw_token(window - 1))
