import asyncio
import json
import logging
import os
import uuid
import hashlib
from typing import AsyncGenerator, Any
import tempfile

from openai_codex import AsyncCodex, CodexConfig
from ..github_auth import build_gh_env

logger = logging.getLogger("infra-agent.codex")

def _token_key(token: str) -> str:
    return hashlib.sha256((token or "empty").encode()).hexdigest()[:16]

async def validate_api_key(api_key: str, auth_method: str = "openai", bedrock_region: str = "us-east-1", ollama_base_url: str = "") -> dict[str, Any]:
    if not api_key and auth_method != "ollama":
        return {"valid": False, "error": "No API key provided"}
    
    if auth_method == "ollama":
        user_label = f"Ollama ({ollama_base_url})"
    elif auth_method == "chatgpt":
        user_label = "ChatGPT Subscription User"
    else:
        user_label = "OpenAI User" if auth_method == "openai" else f"Bedrock ({bedrock_region})"
        
    return {"valid": True, "user": user_label}

async def list_models(api_key: str, auth_method: str = "openai", bedrock_region: str = "us-east-1", ollama_base_url: str = "") -> list[dict[str, Any]]:
    if auth_method == "bedrock":
        # Bedrock models for Codex (usually you'd fetch from AWS or return known ones)
        # We return some known OpenAI models if Bedrock supports them, or just standard ones.
        return [{"id": "gpt-5.4", "name": "gpt-5.4", "supportsReasoning": True},
                {"id": "gpt-5.5", "name": "gpt-5.5", "supportsReasoning": True},
                {"id": "gpt-5.4-mini", "name": "gpt-5.4-mini", "supportsReasoning": True},
                {"id": "gpt-5.3-codex-spark", "name": "gpt-5.3-codex-spark", "supportsReasoning": True}]
    elif auth_method == "chatgpt":
        return [{"id": "gpt-5.5", "name": "gpt-5.5", "supportsReasoning": True},
                {"id": "gpt-5.4", "name": "gpt-5.4", "supportsReasoning": True},
                {"id": "gpt-5.4-mini", "name": "gpt-5.4-mini", "supportsReasoning": True},
                {"id": "gpt-5.3-codex-spark", "name": "gpt-5.3-codex-spark", "supportsReasoning": True},
                {"id": "o1", "name": "o1", "supportsReasoning": True},
                {"id": "o3-mini", "name": "o3-mini", "supportsReasoning": True}]
    else:
        import httpx
        url = "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        
        if auth_method == "ollama":
            url = (ollama_base_url.rstrip("/") if ollama_base_url else "http://localhost:11434/v1") + "/models"
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.get(url, headers=headers, timeout=5.0)
                resp.raise_for_status()
                data = resp.json()
                models = data.get("data", [])
                
                result_models = [{"id": m.get("id"), "name": m.get("id"), "supportsReasoning": True} for m in models if m.get("id")]
                
                if auth_method != "ollama":
                    allowed_exact = {"gpt-5.4-mini", "gpt-5.4", "gpt-5.5", "gpt-5.3-codex-spark"}
                    result_models = [m for m in result_models if m["id"] in allowed_exact]
                
                return result_models
        except Exception as e:
            logger.error("Error fetching codex models from %s: %s", url, e)
            if auth_method == "ollama":
                return []
            return [{"id": "gpt-5.4", "name": "gpt-5.4", "supportsReasoning": True}]

async def _stream_codex(turn, session_id: str) -> AsyncGenerator[dict, None]:
    async for event in turn.stream():
        logger.debug("Codex Event: %s", event.method)
        # Map Codex stream events to the UI's expected format
        if event.method == "item/agentMessage/delta":
            yield {"type": "delta", "content": event.payload.delta}
        elif event.method == "turn/completed":
            yield {"type": "done", "session_id": session_id}
        elif event.method == "error" or "error" in event.method.lower():
            error_msg = str(getattr(event, 'payload', 'Unknown Error'))
            yield {"type": "error", "message": error_msg}

_SESSION_TO_THREAD = {}

_LOGIN_STATUS = {}
_LOGIN_CODEX_CONTEXTS = {}

async def start_chatgpt_login(session_id: str):
    codex_home = os.path.join(tempfile.gettempdir(), "infra-agent-skills", "codex-homes", str(session_id))
    os.makedirs(codex_home, exist_ok=True)
    env = dict(os.environ)
    env["CODEX_HOME"] = codex_home
    config = CodexConfig(cwd=codex_home, env=env)
    codex = AsyncCodex(config=config)
    await codex.__aenter__()
    
    try:
        login = await codex.login_chatgpt()
        
        async def wait_task():
            try:
                completed = await login.wait()
                _LOGIN_STATUS[session_id] = {"status": "success" if completed.success else "failed"}
            finally:
                await codex.__aexit__(None, None, None)
                _LOGIN_CODEX_CONTEXTS.pop(session_id, None)
                
        # Keep the task reference alive
        _LOGIN_CODEX_CONTEXTS[session_id] = {"codex": codex, "task": asyncio.create_task(wait_task())}
        
        _LOGIN_STATUS[session_id] = {"status": "pending", "auth_url": login.auth_url}
        return {"status": "pending", "auth_url": login.auth_url}
    except Exception as e:
        await codex.__aexit__(None, None, None)
        raise e

def check_chatgpt_login(session_id: str):
    return _LOGIN_STATUS.get(session_id, {"status": "not_started"})

async def run_feature(
    api_key: str,
    prompt: str,
    session_id: str,
    model: str = "gpt-5.4-mini",
    feature_id: str = "playground",
    reasoning_effort: str = "",
    auth_method: str = "openai",
    bedrock_region: str = "us-east-1",
    ollama_base_url: str = "",
    active_skills_dir: str = None,
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    inherit_github_env: bool = True,
    app_session_key: str = "",
) -> AsyncGenerator[dict, None]:
    
    config_dict = {}
    if reasoning_effort:
        config_dict["model_reasoning_effort"] = reasoning_effort
        
    session_key = _token_key(api_key + str(session_id))
    env_vars = dict(os.environ)
    if not inherit_github_env:
        for k in list(env_vars.keys()):
            if k.startswith("GH_") or k.startswith("GITHUB_") or k.startswith("COPILOT_GH"):
                env_vars[k] = ""
    env = env_vars
    
    if gh_cli_token.strip():
        default_host = os.environ.get("GH_CLI_HOSTNAME", "github.com") if inherit_github_env else "github.com"
        ghhost = gh_cli_hostname.strip() if gh_cli_hostname.strip() else default_host
        env.update(build_gh_env(gh_cli_token.strip(), ghhost, session_key))

    if auth_method == "bedrock":
        if "," in api_key:
            env["AWS_ACCESS_KEY_ID"] = api_key.split(",")[0].strip()
            env["AWS_SECRET_ACCESS_KEY"] = api_key.split(",")[1].strip()
        else:
            env["AWS_ACCESS_KEY_ID"] = api_key
        env["AWS_REGION"] = bedrock_region
    elif auth_method == "ollama":
        env["OPENAI_BASE_URL"] = ollama_base_url.rstrip("/") if ollama_base_url else "http://localhost:11434/v1"
        env["OPENAI_API_KEY"] = api_key or "ollama"
    elif auth_method == "chatgpt":
        codex_home = os.path.join(tempfile.gettempdir(), "infra-agent-skills", "codex-homes", str(app_session_key or session_id))
        os.makedirs(codex_home, exist_ok=True)
        env["CODEX_HOME"] = codex_home
    else:
        env["OPENAI_API_KEY"] = api_key
        
    cwd = None
    if session_id:
        cwd = os.path.join(tempfile.gettempdir(), "infra-agent-skills", "active", str(session_id))
        os.makedirs(cwd, exist_ok=True)
        
    codex_config = CodexConfig(cwd=cwd, env=env)

    async with AsyncCodex(config=codex_config) as codex:
        model_provider = "amazon-bedrock" if auth_method == "bedrock" else ("ollama" if auth_method == "ollama" else "openai")
        thread = await codex.thread_start(model=model, config=config_dict, model_provider=model_provider)
        if session_id:
            _SESSION_TO_THREAD[session_id] = thread.id
        
        turn = await thread.turn(prompt)
        
        async for ui_event in _stream_codex(turn, session_id):
            yield ui_event

async def run_followup(
    api_key: str,
    session_id: str,
    query: str,
    model: str = "gpt-5.4-mini",
    reasoning_effort: str = "",
    auth_method: str = "openai",
    bedrock_region: str = "us-east-1",
    ollama_base_url: str = "",
    active_skills_dir: str = None,
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    inherit_github_env: bool = True,
    app_session_key: str = "",
) -> AsyncGenerator[dict, None]:

    session_key = _token_key(api_key + str(session_id))
    env_vars = dict(os.environ)
    if not inherit_github_env:
        for k in list(env_vars.keys()):
            if k.startswith("GH_") or k.startswith("GITHUB_") or k.startswith("COPILOT_GH"):
                env_vars[k] = ""
    env = env_vars
    
    if gh_cli_token.strip():
        default_host = os.environ.get("GH_CLI_HOSTNAME", "github.com") if inherit_github_env else "github.com"
        ghhost = gh_cli_hostname.strip() if gh_cli_hostname.strip() else default_host
        env.update(build_gh_env(gh_cli_token.strip(), ghhost, session_key))
        

    if auth_method == "bedrock":
        if "," in api_key:
            env["AWS_ACCESS_KEY_ID"] = api_key.split(",")[0].strip()
            env["AWS_SECRET_ACCESS_KEY"] = api_key.split(",")[1].strip()
        else:
            env["AWS_ACCESS_KEY_ID"] = api_key
        env["AWS_REGION"] = bedrock_region
    elif auth_method == "ollama":
        env["OPENAI_BASE_URL"] = ollama_base_url.rstrip("/") if ollama_base_url else "http://localhost:11434/v1"
        env["OPENAI_API_KEY"] = api_key or "ollama"
    elif auth_method == "chatgpt":
        codex_home = os.path.join(tempfile.gettempdir(), "infra-agent-skills", "codex-homes", str(app_session_key or session_id))
        os.makedirs(codex_home, exist_ok=True)
        env["CODEX_HOME"] = codex_home
    else:
        env["OPENAI_API_KEY"] = api_key
        
    cwd = None
    if session_id:
        cwd = os.path.join(tempfile.gettempdir(), "infra-agent-skills", "active", str(session_id))
        os.makedirs(cwd, exist_ok=True)
        
    codex_config = CodexConfig(cwd=cwd, env=env)

    async with AsyncCodex(config=codex_config) as codex:
        thread_id = _SESSION_TO_THREAD.get(session_id, session_id)
        thread = await codex.thread_resume(thread_id)
        
        turn = await thread.turn(query)
        
        async for ui_event in _stream_codex(turn, session_id):
            yield ui_event
