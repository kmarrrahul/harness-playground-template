import base64
import json
import secrets
import logging
from fastapi import Request

logger = logging.getLogger(__name__)

# ── Global session encryption key ──
APP_SESSION_KEY = secrets.token_hex(16)

def _deobfuscate_payload(b64_text: str, key: str) -> str:
    key_bytes = key.encode('utf-8')
    text_bytes = base64.b64decode(b64_text)
    res = bytearray()
    for i in range(len(text_bytes)):
        res.append(text_bytes[i] ^ key_bytes[i % len(key_bytes)])
    return res.decode('utf-8')

async def _get_json_body(request: Request) -> dict:
    raw_body = await request.json()
    if "encrypted_payload" in raw_body:
        decrypted_str = _deobfuscate_payload(raw_body["encrypted_payload"], APP_SESSION_KEY)
        return json.loads(decrypted_str)
    return raw_body

def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""

_SUPPORTED_PROVIDERS = set()

try:
    from .providers import copilot_service
    _SUPPORTED_PROVIDERS.add("copilot")
except ImportError:
    copilot_service = None

try:
    from .providers import antigravity_service
    _SUPPORTED_PROVIDERS.add("antigravity")
except ImportError:
    antigravity_service = None

try:
    from .providers import cursor_service
    _SUPPORTED_PROVIDERS.add("cursor")
except ImportError:
    cursor_service = None

try:
    from .providers import claude_service
    _SUPPORTED_PROVIDERS.add("claude")
except ImportError:
    claude_service = None

try:
    from .providers import codex_service
    _SUPPORTED_PROVIDERS.add("codex")
except ImportError:
    codex_service = None

from .core.prompts import playground

_PROMPT_BUILDERS: dict[str, object] = {
    "playground": lambda params, diag: playground(params.get("prompt", ""), diag),
}
