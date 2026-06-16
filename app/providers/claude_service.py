import asyncio
import json
import logging
import os
import hashlib
from typing import Any, AsyncGenerator

from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock, UserMessage, ToolResultBlock, PermissionResultAllow
from ..core.mcp_config import get_base_mcp_config
from ..github_auth import build_gh_env

logger = logging.getLogger("infra-agent.claude")

def _token_key(token: str) -> str:
    return hashlib.sha256((token or "empty").encode()).hexdigest()[:16]

async def validate_api_key(api_key: str, auth_method: str = "anthropic", bedrock_region: str = "us-east-1") -> dict[str, Any]:
    """
    Validate an Anthropic API key or Bedrock credentials.
    """
    if not api_key:
        return {"valid": False, "error": "No API key provided"}
    
    if auth_method == "bedrock":
        # Usually Bedrock tokens can be anything or start with bedrock-api-key-
        return {"valid": True, "user": f"Bedrock ({bedrock_region})"}
    elif auth_method == "vertex":
        return {"valid": True, "user": "Vertex AI"}
    elif auth_method == "custom":
        return {"valid": True, "user": "Custom API"}
    
    if api_key.startswith("sk-ant-"):
        # Could do a quick test query here, but format check is fast
        return {"valid": True, "user": "Anthropic Key"}
    
    return {"valid": False, "error": "Invalid Anthropic API key format. Should start with 'sk-ant-'"}

async def list_models(api_key: str, auth_method: str = "anthropic", region: str = "us-east-1", base_url: str = "") -> list[dict[str, str]]:
    """
    Return available Claude models.
    """
    if auth_method == "bedrock":
        import httpx
        import asyncio
        url_fm = f"https://bedrock.{region}.amazonaws.com/foundation-models?byProvider=Anthropic"
        url_ip = f"https://bedrock.{region}.amazonaws.com/inference-profiles"
        try:
            async with httpx.AsyncClient() as client:
                headers = {"Authorization": f"Bearer {api_key}"}
                
                async def fetch_fm():
                    resp = await client.get(url_fm, headers=headers, timeout=5.0)
                    if resp.status_code == 200:
                        return resp.json().get("modelSummaries", [])
                    return []
                    
                async def fetch_ip():
                    resp = await client.get(url_ip, headers=headers, timeout=5.0)
                    if resp.status_code == 200:
                        return resp.json().get("inferenceProfileSummaries", [])
                    return []
                    
                fms, ips = await asyncio.gather(fetch_fm(), fetch_ip(), return_exceptions=True)
                
                valid_models = []
                seen_ids = set()
                
                # Add inference profiles that seem to be Anthropic
                if isinstance(ips, list):
                    for p in ips:
                        pid = p.get("inferenceProfileId", "")
                        # We only want system-defined cross-region or specific Anthropic profiles
                        if "anthropic" in pid.lower():
                            valid_models.append({
                                "id": pid,
                                "name": p.get("inferenceProfileName", pid) + " (Profile)"
                            })
                            seen_ids.add(pid)
                            
                # Add foundation models that support ON_DEMAND
                if isinstance(fms, list):
                    for m in fms:
                        mid = m["modelId"]
                        if mid in seen_ids:
                            continue
                        supported_types = m.get("inferenceTypesSupported", [])
                        if "ON_DEMAND" in supported_types:
                            valid_models.append({
                                "id": mid,
                                "name": m.get("modelName", mid)
                            })
                            seen_ids.add(mid)
                            
                if valid_models:
                    return valid_models
                    
        except Exception as e:
            logger.warning("Failed to list bedrock models dynamically via HTTP: %s", e)
            
        # Fallback to static if HTTP fetch fails
        return [
            {"id": "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "name": "Claude 3.5 Sonnet v2 (Bedrock)"},
            {"id": "us.anthropic.claude-3-5-haiku-20241022-v1:0", "name": "Claude 3.5 Haiku (Bedrock)"},
            {"id": "us.anthropic.claude-3-opus-20240229-v1:0", "name": "Claude 3 Opus (Bedrock)"},
            {"id": "anthropic.claude-3-sonnet-20240229-v1:0", "name": "Claude 3 Sonnet (Bedrock)"},
            {"id": "anthropic.claude-3-haiku-20240307-v1:0", "name": "Claude 3 Haiku (Bedrock)"}
        ]
        
    if auth_method in ("anthropic", "custom"):
        import httpx
        url = "https://api.anthropic.com/v1/models"
        if auth_method == "custom" and base_url:
            url = base_url.rstrip("/") + "/models"
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01"
                    },
                    timeout=5.0
                )
                resp.raise_for_status()
                data = resp.json()
                models = data.get("data", [])
                return [{"id": m.get("id"), "name": m.get("display_name", m.get("id")), "supportsReasoning": False} for m in models]
        except Exception as e:
            logger.warning("Failed to list anthropic models dynamically from %s: %s", url, e)
            
    return [
        {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet"},
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
        {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus"}
    ]

async def _yield_claude_stream(
    api_key: str, 
    prompt: str, 
    model: str | None = None,
    session_id: str | None = None,
    resume: str | None = None,
    auth_method: str = "anthropic",
    bedrock_region: str = "us-east-1",
    vertex_project: str = "",
    vertex_region: str = "us-central1",
    base_url: str = "",

    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    active_skills_dir: str | None = None,
    inherit_github_env: bool = True
) -> AsyncGenerator[dict[str, Any], None]:
    
    session_key = _token_key(api_key + str(session_id))
    env_vars = dict(os.environ)
    if not inherit_github_env:
        for k in list(env_vars.keys()):
            if k.startswith("GH_") or k.startswith("GITHUB_") or k.startswith("COPILOT_GH"):
                env_vars[k] = ""
    env = env_vars
    
    # Configure base MCP servers
    mcp_config = get_base_mcp_config(session_key=session_key)
        
    if gh_cli_token.strip():
        default_host = os.environ.get("GH_CLI_HOSTNAME", "github.com") if inherit_github_env else "github.com"
        ghhost = gh_cli_hostname.strip() if gh_cli_hostname.strip() else default_host
        env.update(build_gh_env(gh_cli_token.strip(), ghhost, session_key))
    if auth_method == "bedrock":
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        env["AWS_BEARER_TOKEN_BEDROCK"] = api_key
        env["AWS_REGION"] = bedrock_region
        # If model is not explicitly bedrock formatted, usually Claude CLI handles it, but let's default appropriately
        if not model:
            model = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
    elif auth_method == "vertex":
        env["CLAUDE_CODE_USE_VERTEX"] = "1"
        if vertex_project:
            env["ANTHROPIC_VERTEX_PROJECT_ID"] = vertex_project
            env["CLOUD_ML_PROJECT_ID"] = vertex_project
        if vertex_region:
            env["ANTHROPIC_VERTEX_REGION"] = vertex_region
            env["CLOUD_ML_REGION"] = vertex_region
        if api_key:
            env["GOOGLE_OAUTH_TOKEN"] = api_key
        if not model:
            model = "claude-3-5-sonnet-v2@20241022"
    else:
        env["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            env["ANTHROPIC_BASE_URL"] = base_url
        if not model:
            model = "claude-3-5-sonnet-20241022"

    allowed_tools = ["Bash", "Read", "Write", "Edit", "Replace", "MultiReplace", "Glob", "Grep", "LS", "View", "Search", "FetchWeb", "GetUrl", "ReadUrl", "Store", "Remember", "Think", "Plan", "Review"]
    setting_sources = None

    import tempfile
    # ALWAYS use a constant working directory for the session so Claude Code CLI
    # does not lose the session if the user toggles Agent Skills on/off between requests.
    # This path matches the one generated by skills.compile_active_skills.
    cwd = os.path.join(tempfile.gettempdir(), "infra-agent-skills", "active", str(session_id))
    os.makedirs(cwd, exist_ok=True)

    if active_skills_dir:
        allowed_tools.append("Skill")
        setting_sources = ["project"]

    options = ClaudeAgentOptions(
        env=env,
        model=model,
        session_id=session_id if not resume else None,
        resume=resume,
        permission_mode="auto",
        allowed_tools=allowed_tools,
        setting_sources=setting_sources,
        mcp_servers=mcp_config,
        cwd=cwd
    )
    
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # The UI expects 'content' at the top level for delta/message
                        yield {
                            "type": "message",
                            "content": block.text
                        }
                    elif isinstance(block, ToolUseBlock):
                        yield {
                            "type": "tool_start",
                            "name": block.name,
                            "tool_id": block.id,
                            "input": block.input
                        }
            elif isinstance(message, UserMessage):
                for block in getattr(message, 'content', []):
                    if isinstance(block, ToolResultBlock):
                        # The UI ends a tool when it receives tool_end
                        # We use the tool_id if available, otherwise just signal the end
                        yield {
                            "type": "tool_end",
                            "name": getattr(block, 'name', 'Unknown'),
                            "tool_id": block.tool_use_id
                        }
            
            # Find the session_id to return in done
            current_session_id = getattr(message, 'session_id', session_id)
            
            # If the run finishes, we yield done
            if getattr(message, 'subtype', None) == 'success':
                yield {
                    "type": "done",
                    "session_id": current_session_id
                }
    except Exception as e:
        logger.exception("Claude SDK Error")
        yield {"type": "error", "message": str(e)}

async def run_feature(
    api_key: str,
    prompt: str,
    session_id: str | None = None,
    model: str | None = None,
    feature_id: str | None = None,
    reasoning_effort: str | None = None,
    system_instructions: str = "",
    auth_method: str = "anthropic",
    bedrock_region: str = "us-east-1",
    vertex_project: str = "",
    vertex_region: str = "us-central1",
    base_url: str = "",
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    active_skills_dir: str | None = None,
    inherit_github_env: bool = True
) -> AsyncGenerator[dict[str, Any], None]:
    """Run a feature using Claude."""
    async for event in _yield_claude_stream(
        api_key=api_key, 
        prompt=prompt, 
        model=model,
        session_id=session_id,
        auth_method=auth_method,
        bedrock_region=bedrock_region,
        vertex_project=vertex_project,
        vertex_region=vertex_region,
        base_url=base_url,
        gh_cli_token=gh_cli_token,
        gh_cli_hostname=gh_cli_hostname,
        active_skills_dir=active_skills_dir,
        inherit_github_env=inherit_github_env
    ):
        yield event

async def run_followup(
    api_key: str,
    session_id: str,
    query: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
    auth_method: str = "anthropic",
    bedrock_region: str = "us-east-1",
    vertex_project: str = "",
    vertex_region: str = "us-central1",
    base_url: str = "",
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    active_skills_dir: str | None = None,
    inherit_github_env: bool = True
) -> AsyncGenerator[dict[str, Any], None]:
    """Run a followup using Claude."""
    async for event in _yield_claude_stream(
        api_key=api_key, 
        prompt=query, 
        model=model, 
        resume=session_id,
        session_id=session_id,
        auth_method=auth_method,
        bedrock_region=bedrock_region,
        vertex_project=vertex_project,
        vertex_region=vertex_region,
        base_url=base_url,
        gh_cli_token=gh_cli_token,
        gh_cli_hostname=gh_cli_hostname,
        active_skills_dir=active_skills_dir,
        inherit_github_env=inherit_github_env
    ):
        yield event
