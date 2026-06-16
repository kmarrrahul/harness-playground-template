"""Cursor SDK integration for Infra Agent."""
import asyncio
import logging
import os
import hashlib

from ..github_auth import build_gh_env

logger = logging.getLogger(__name__)

def _token_key(token: str) -> str:
    return hashlib.sha256((token or "empty").encode()).hexdigest()[:16]

# We'll use the sync client for simplicity and global session if async is too complex,
# or we'll manage an async client globally.

_active_sessions = {}
_client = None

async def _get_client():
    global _client
    if _client is None:
        from cursor_sdk import AsyncClient
        # launch_bridge returns an async context manager
        cm = await AsyncClient.launch_bridge(workspace=os.getcwd())
        _client = await cm.__aenter__()
    return _client

async def validate_api_key(api_key: str) -> dict:
    if not api_key:
        return {"valid": False, "error": "No API key provided"}
    try:
        client = await _get_client()
        await client.models.list(api_key=api_key)
        return {"valid": True, "user": "Valid API Key"}
    except Exception as e:
        return {"valid": False, "error": str(e)}

async def list_models(token: str) -> list[dict]:
    try:
        client = await _get_client()
        models = await client.models.list(api_key=token)
        return [
            {"id": m.id, "name": getattr(m, 'name', m.id), "supportsReasoning": getattr(m, 'supports_reasoning', False)}
            for m in models
        ]
    except Exception as e:
        logger.error("Error listing cursor models: %s", e)
        return []

async def run_feature(
    api_key, 
    prompt, 
    model, 
    feature_id, 
    reasoning_effort="", 
    system_instructions="",
    gh_cli_token="",
    gh_cli_hostname="",
    active_skills_dir=None,
    inherit_github_env=True
):
    try:
        from cursor_sdk import LocalAgentOptions
        client = await _get_client()

        session_key = _token_key(api_key + str(feature_id))
        env_vars = dict(os.environ)
        if not inherit_github_env:
            for k in list(env_vars.keys()):
                if k.startswith("GH_") or k.startswith("GITHUB_") or k.startswith("COPILOT_GH"):
                    env_vars.pop(k, None)
        
        if gh_cli_token.strip():
            default_host = os.environ.get("GH_CLI_HOSTNAME", "github.com") if inherit_github_env else "github.com"
            ghhost = gh_cli_hostname.strip() if gh_cli_hostname.strip() else default_host
            env_vars.update(build_gh_env(gh_cli_token.strip(), ghhost, session_key))

        cwd = os.getcwd()
        if active_skills_dir:
            import shutil
            rules_dir = os.path.join(cwd, ".cursor", "rules")
            os.makedirs(rules_dir, exist_ok=True)
            for skill_id in os.listdir(active_skills_dir):
                skill_path = os.path.join(active_skills_dir, skill_id)
                if os.path.isdir(skill_path):
                    src_instr = os.path.join(skill_path, "instruction.md")
                    if os.path.exists(src_instr):
                        dst_rule = os.path.join(rules_dir, f"{skill_id}.mdc")
                        shutil.copyfile(src_instr, dst_rule)

        agent = await client.agents.create(
            api_key=api_key,
            model=model,
            local=LocalAgentOptions(cwd=cwd, env=env_vars)
        )
        _active_sessions[agent.agent_id] = agent
        
        run = await agent.send(prompt)
        yield {"type": "status", "status": "running"}
        
        async for message in run.messages():
            if message.type == "assistant":
                for block in getattr(message.message, 'content', []):
                    if getattr(block, 'type', '') == "text":
                        yield {"type": "delta", "content": block.text}
            elif message.type == "thinking":
                yield {"type": "reasoning_delta", "content": message.text}
            elif message.type == "tool_call":
                tool_id = getattr(message, 'id', message.name)
                if getattr(message, 'status', '') == "started":
                    yield {"type": "tool_start", "name": message.name, "tool_id": tool_id}
                elif getattr(message, 'status', '') in ("finished", "error"):
                    yield {"type": "tool_end", "tool_id": tool_id}
        
        yield {"type": "done", "session_id": agent.agent_id}
        
    except Exception as e:
        logger.exception("Cursor run_feature error")
        yield {"type": "error", "message": str(e)}

async def run_followup(
    api_key, 
    session_id, 
    query, 
    model, 
    reasoning_effort="",
    gh_cli_token="",
    gh_cli_hostname="",
    active_skills_dir=None,
    inherit_github_env=True
):
    try:
        agent = _active_sessions.get(session_id)
        if not agent:
            yield {"type": "error", "message": "Session not found."}
            return
            
        run = await agent.send(query)
        yield {"type": "status", "status": "running"}
        
        async for message in run.messages():
            if message.type == "assistant":
                for block in getattr(message.message, 'content', []):
                    if getattr(block, 'type', '') == "text":
                        yield {"type": "delta", "content": block.text}
            elif message.type == "thinking":
                yield {"type": "reasoning_delta", "content": message.text}
            elif message.type == "tool_call":
                tool_id = getattr(message, 'id', message.name)
                if getattr(message, 'status', '') == "started":
                    yield {"type": "tool_start", "name": message.name, "tool_id": tool_id}
                elif getattr(message, 'status', '') in ("finished", "error"):
                    yield {"type": "tool_end", "tool_id": tool_id}
                    
        yield {"type": "done", "session_id": session_id}
        
    except Exception as e:
        logger.exception("Cursor run_followup error")
        yield {"type": "error", "message": str(e)}
