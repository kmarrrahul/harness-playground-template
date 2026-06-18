import os
import json
import uuid
import pathlib
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..schemas.models import RunRequest, FollowupRequest
from .. import skills
from ..dependencies import _get_json_body, _extract_token, _SUPPORTED_PROVIDERS, _PROMPT_BUILDERS, logger
from ..dependencies import copilot_service, antigravity_service, cursor_service, claude_service, codex_service

router = APIRouter()

async def fetch_openai_models(base_url: str, api_key: str) -> list:
    import httpx
    url = base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            result = []
            for m in models:
                mid = m.get("id")
                if not mid: continue
                if mid.startswith("models/"):
                    mid = mid[7:]
                result.append({"id": mid, "name": mid, "supportsReasoning": False})
            return result
    except Exception as e:
        logger.error("Error fetching models from %s: %s", url, e)
        return []

@router.post("/api/models")
async def get_models(request: Request):
    """Return available models for the specified provider."""
    raw_body = await _get_json_body(request)
    provider = raw_body.get("provider", "copilot")
    auth_method = raw_body.get("auth_method", "anthropic")
    base_url = raw_body.get("base_url", "")
    region = raw_body.get("region", "us-east-1")
    
    token = raw_body.get("__auth_token") if "__auth_token" in raw_body else _extract_token(request)
    
    if not token:
        return JSONResponse({"error": "Missing Authorization header"}, status_code=401)

    if provider == "antigravity":
        if not antigravity_service:
            return JSONResponse({"error": "Antigravity SDK is not installed."}, status_code=501)
        models = await antigravity_service.list_models(token)
    elif provider == "cursor":
        if not cursor_service:
            return JSONResponse({"error": "Cursor SDK is not installed."}, status_code=501)
        models = await cursor_service.list_models(token)
    elif provider == "claude":
        if not claude_service:
            return JSONResponse({"error": "Claude Agent is not installed."}, status_code=501)
        models = await claude_service.list_models(token, auth_method, region, base_url)
    elif provider == "codex":
        if not codex_service:
            return JSONResponse({"error": "Codex SDK is not installed."}, status_code=501)
        models = await codex_service.list_models(
            token, auth_method=auth_method, bedrock_region=region, ollama_base_url=base_url
        )
    else:
        if auth_method in ("openai", "azure", "anthropic") and base_url:
            models = await fetch_openai_models(base_url, token)
        else:
            if not copilot_service:
                return JSONResponse({"error": "GitHub Copilot SDK is not installed."}, status_code=501)
            models = await copilot_service.list_models(token)
    return JSONResponse({"models": models})

@router.post("/api/run")
async def run_feature(request: Request):
    raw_body = await _get_json_body(request)
    body = RunRequest(**raw_body)
    token = raw_body.get("__auth_token") if "__auth_token" in raw_body else _extract_token(request)
    
    if not token:
        return JSONResponse({"error": "Missing Authorization header"}, status_code=401)

    if not body.session_id:
        body.session_id = str(uuid.uuid4())

    provider = body.provider or "copilot"
    if provider not in _SUPPORTED_PROVIDERS:
        return JSONResponse({"error": f"Unknown provider: {provider}"}, status_code=400)

    auth_method = "OAuth" if token.startswith(("gho_", "ghu_")) else "PAT/API-Key"
    logger.info("run_feature: provider=%s feature=%s model=%s reasoning_effort=%s auth=%s",
                provider, body.feature, body.model, body.reasoning_effort or "(none)", auth_method)

    builder = _PROMPT_BUILDERS.get(body.feature)
    if not builder:
        return JSONResponse({"error": f"Unknown feature: {body.feature}"}, status_code=400)

    prompt = builder(body.params, body.generate_diagram)
    gh_cli_token = body.gh_cli_token.strip()
    if not gh_cli_token:
        gh_cli_token = os.environ.get("GH_TOKEN_CLI", "").strip()

    active_skills_dir = None
    if body.enabled_skills:
        workspace_id = copilot_service._token_key(token) if copilot_service else "default"
        run_session_id = body.session_id
        active_skills_dir = skills.compile_active_skills(body.enabled_skills, workspace_id, run_session_id)

    if provider == "antigravity":
        async def _ag_generator():
            try:
                async for event in antigravity_service.run_feature(
                    api_key=token, prompt=prompt, model=body.model,
                    feature_id=body.feature, reasoning_effort=body.reasoning_effort,
                    system_instructions="", gh_cli_token=gh_cli_token, gh_cli_hostname=body.gh_cli_hostname,
                    active_skills_dir=active_skills_dir, inherit_github_env=body.inherit_github_env,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("run_feature error (antigravity)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_ag_generator())

    elif provider == "cursor":
        async def _cursor_generator():
            try:
                async for event in cursor_service.run_feature(
                    api_key=token, prompt=prompt, model=body.model,
                    feature_id=body.feature, reasoning_effort=body.reasoning_effort,
                    system_instructions="", gh_cli_token=gh_cli_token, gh_cli_hostname=body.gh_cli_hostname,
                    active_skills_dir=active_skills_dir, inherit_github_env=body.inherit_github_env,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("run_feature error (cursor)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_cursor_generator())

    elif provider == "claude":
        async def _claude_generator():
            try:
                async for event in claude_service.run_feature(
                    api_key=token, prompt=prompt, session_id=body.session_id, model=body.model,
                    feature_id=body.feature, reasoning_effort=body.reasoning_effort, system_instructions="",
                    auth_method=body.claude_auth_method, bedrock_region=body.claude_bedrock_region,
                    vertex_project=body.claude_vertex_project, vertex_region=body.claude_vertex_region,
                    base_url=body.claude_base_url, gh_cli_token=gh_cli_token, gh_cli_hostname=body.gh_cli_hostname,
                    active_skills_dir=active_skills_dir, inherit_github_env=body.inherit_github_env,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("run_feature error (claude)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_claude_generator())

    elif provider == "codex":
        async def _codex_generator():
            try:
                async for event in codex_service.run_feature(
                    api_key=token or body.codex_api_key, prompt=prompt, session_id=body.session_id, model=body.model,
                    feature_id=body.feature, reasoning_effort=body.reasoning_effort,
                    auth_method=body.codex_auth_method, bedrock_region=body.codex_bedrock_region,
                    ollama_base_url=body.codex_ollama_base_url,
                    active_skills_dir=active_skills_dir,
                    gh_cli_token=gh_cli_token,
                    gh_cli_hostname=body.gh_cli_hostname,
                    inherit_github_env=body.inherit_github_env,
                    app_session_key=body.app_session_key,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("run_feature error (codex)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_codex_generator())

    else:
        async def _copilot_generator():
            byok_dict = {}
            if body.copilot_byok_type:
                byok_dict = {
                    "type": body.copilot_byok_type, "base_url": body.copilot_byok_base_url,
                    "wire_api": body.copilot_byok_wire_api, "api_key": body.copilot_byok_api_key,
                }
            try:
                async for event in copilot_service.run_feature(
                    token, prompt, body.model, feature_id=body.feature, gh_cli_token=gh_cli_token,
                    gh_cli_hostname=body.gh_cli_hostname, byok=byok_dict, active_skills_dir=active_skills_dir,
                    inherit_github_env=body.inherit_github_env,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("run_feature error (copilot)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_copilot_generator())

@router.post("/api/followup")
async def followup(request: Request):
    raw_body = await _get_json_body(request)
    body = FollowupRequest(**raw_body)
    token = raw_body.get("__auth_token") if "__auth_token" in raw_body else _extract_token(request)
    
    if not token:
        return JSONResponse({"error": "Missing Authorization header"}, status_code=401)

    if not body.session_id or not body.query.strip():
        return JSONResponse({"error": "session_id and query are required"}, status_code=400)

    provider = body.provider or "copilot"
    logger.info("followup: provider=%s session_id=%s", provider, body.session_id)

    gh_cli_token = body.gh_cli_token.strip()
    if not gh_cli_token:
        gh_cli_token = os.environ.get("GH_TOKEN_CLI", "").strip()

    active_skills_dir = None
    if body.enabled_skills:
        workspace_id = copilot_service._token_key(token) if copilot_service else "default"
        active_skills_dir = skills.compile_active_skills(body.enabled_skills, workspace_id, body.session_id)

    if provider == "antigravity":
        async def _ag_followup():
            try:
                async for event in antigravity_service.run_followup(
                    api_key=token, session_id=body.session_id, query=body.query,
                    model=body.model, reasoning_effort=body.reasoning_effort, gh_cli_token=gh_cli_token,
                    gh_cli_hostname=body.gh_cli_hostname, active_skills_dir=active_skills_dir,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("followup error (antigravity)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_ag_followup())

    elif provider == "cursor":
        async def _cursor_followup():
            try:
                async for event in cursor_service.run_followup(
                    api_key=token, session_id=body.session_id, query=body.query,
                    model=body.model, reasoning_effort=body.reasoning_effort, gh_cli_token=gh_cli_token,
                    gh_cli_hostname=body.gh_cli_hostname, active_skills_dir=active_skills_dir,
                    inherit_github_env=body.inherit_github_env,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("followup error (cursor)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_cursor_followup())

    elif provider == "claude":
        async def _claude_followup():
            try:
                async for event in claude_service.run_followup(
                    api_key=token, session_id=body.session_id, query=body.query,
                    model=body.model, reasoning_effort=body.reasoning_effort, auth_method=body.claude_auth_method,
                    bedrock_region=body.claude_bedrock_region, vertex_project=body.claude_vertex_project,
                    vertex_region=body.claude_vertex_region, base_url=body.claude_base_url,
                    gh_cli_token=gh_cli_token, gh_cli_hostname=body.gh_cli_hostname, active_skills_dir=active_skills_dir,
                    inherit_github_env=body.inherit_github_env,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("followup error (claude)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_claude_followup())

    elif provider == "codex":
        async def _codex_followup():
            try:
                async for event in codex_service.run_followup(
                    api_key=token or body.codex_api_key, session_id=body.session_id, query=body.query,
                    model=body.model, reasoning_effort=body.reasoning_effort,
                    auth_method=body.codex_auth_method, bedrock_region=body.codex_bedrock_region,
                    ollama_base_url=body.codex_ollama_base_url,
                    active_skills_dir=active_skills_dir,
                    gh_cli_token=gh_cli_token,
                    gh_cli_hostname=body.gh_cli_hostname,
                    inherit_github_env=body.inherit_github_env,
                    app_session_key=body.app_session_key,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("followup error (codex)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_codex_followup())

    else:
        async def _copilot_followup():
            byok_dict = {}
            if body.copilot_byok_type:
                byok_dict = {
                    "type": body.copilot_byok_type, "base_url": body.copilot_byok_base_url,
                    "wire_api": body.copilot_byok_wire_api, "api_key": body.copilot_byok_api_key,
                }
            try:
                async for event in copilot_service.run_followup(
                    token, body.session_id, body.query, body.model,
                    reasoning_effort=body.reasoning_effort, byok=byok_dict, gh_cli_token=body.gh_cli_token,
                    gh_cli_hostname=body.gh_cli_hostname, active_skills_dir=active_skills_dir,
                    inherit_github_env=body.inherit_github_env,
                ):
                    yield json.dumps(event)
            except Exception as exc:
                logger.exception("followup error (copilot)")
                yield json.dumps({"type": "error", "message": str(exc)})
        return EventSourceResponse(_copilot_followup())
