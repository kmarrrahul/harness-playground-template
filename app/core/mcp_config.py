"""
Base MCP server configuration.

Provides configuration for optional MCP servers. 
In the default template, no external MCP servers are injected since
the focus is purely on the terminal and shell capabilities.
"""
import logging
import os
import shutil
import tempfile

logger = logging.getLogger(__name__)

# ── Temp directory for per-session files ──────────────────────────
_TEMP_BASE_DIR = os.path.join(tempfile.gettempdir(), "harness-agent-temp")

def _ensure_temp_dir(session_key: str) -> str:
    """Create a unique temp directory for a session."""
    temp_dir = os.path.join(_TEMP_BASE_DIR, session_key)
    os.makedirs(temp_dir, mode=0o700, exist_ok=True)
    return temp_dir

def cleanup_creds_dir(session_key: str) -> None:
    """Remove the temp directory for a session."""
    temp_dir = os.path.join(_TEMP_BASE_DIR, session_key)
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.debug("Cleaned up temp dir for session key %s", session_key)

def get_base_mcp_config(session_key: str = "") -> dict:
    """
    Return the combined MCP server config dict.
    
    By default, the harness relies purely on the native shell/terminal tools
    and does not inject any external MCP servers like filesystem or terraform.
    """
    config: dict = {}
    return config
