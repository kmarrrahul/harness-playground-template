"""GitHub CLI authentication environment builders."""
import logging
import os
import stat
import yaml

from .core.mcp_config import _ensure_temp_dir

logger = logging.getLogger(__name__)

def _write_gh_hosts_file(session_key: str, token: str, host: str = "github.com") -> str:
    """Write a gh CLI hosts.yml file to a per-session temp path.
    
    This prevents the Copilot CLI and other tools from scrubbing explicit GH_TOKEN
    env vars by injecting the credentials securely via a temp config directory.
    Returns the path to the directory (for GH_CONFIG_DIR).
    """
    gh_dir = _ensure_temp_dir(session_key)
    hosts_path = os.path.join(gh_dir, "hosts.yml")
    
    # We just create a minimal hosts.yml to authenticate the specific host
    config_data = {
        host: {
            "oauth_token": token,
            "user": "infra-agent-user",
            "git_protocol": "https"
        }
    }
    with open(hosts_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False)
    os.chmod(hosts_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    logger.debug("Wrote gh hosts.yml for host %s (session %s)", host, session_key)
    return gh_dir

def build_gh_env(token: str, host: str = "github.com", session_key: str = "") -> dict[str, str]:
    """Build GitHub CLI environment variables, using GH_CONFIG_DIR for true isolation.
    
    If session_key is provided, writes a per-session hosts.yml and sets GH_CONFIG_DIR
    so that shell tools (like Copilot's `bash`) do not accidentally scrub explicit
    token env vars like GH_TOKEN or GH_ENTERPRISE_TOKEN.
    """
    env: dict[str, str] = {}
    if not token:
        return env
        
    env["GH_TOKEN"] = token
    if host and host != "github.com":
        env["GH_HOST"] = host
        env["GH_ENTERPRISE_TOKEN"] = token
        
    if session_key:
        config_dir = _write_gh_hosts_file(session_key, token, host)
        env["GH_CONFIG_DIR"] = config_dir
        
    return env
