from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import JSONResponse
import hashlib
import os

from .. import skills
from ..dependencies import _extract_token, _SUPPORTED_PROVIDERS, copilot_service

router = APIRouter()

@router.get("/api/skills")
async def get_skills(request: Request):
    token = _extract_token(request)
    if not token:
        return JSONResponse({"error": "Missing Authorization header"}, status_code=401)
    
    workspace_id = copilot_service._token_key(token) if "copilot" in _SUPPORTED_PROVIDERS and copilot_service else hashlib.sha256(token.encode()).hexdigest()[:16]
    return JSONResponse(skills.list_skills(workspace_id))

@router.post("/api/skills/upload")
async def upload_skill(request: Request, file: UploadFile = File(...)):
    token = _extract_token(request)
    if not token:
        return JSONResponse({"error": "Missing Authorization header"}, status_code=401)
        
    workspace_id = copilot_service._token_key(token) if "copilot" in _SUPPORTED_PROVIDERS and copilot_service else hashlib.sha256(token.encode()).hexdigest()[:16]
    
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
        
    try:
        skill_id = skills.extract_uploaded_skill(tmp_path, workspace_id)
        os.unlink(tmp_path)
        return JSONResponse({"success": True, "skill_id": skill_id})
    except Exception as exc:
        os.unlink(tmp_path)
        return JSONResponse({"error": str(exc)}, status_code=400)

@router.post("/api/skills/text")
async def upload_skill_text(request: Request):
    token = _extract_token(request)
    if not token:
        return JSONResponse({"error": "Missing Authorization header"}, status_code=401)
        
    workspace_id = copilot_service._token_key(token) if "copilot" in _SUPPORTED_PROVIDERS and copilot_service else hashlib.sha256(token.encode()).hexdigest()[:16]
    body = await request.json()
    
    skill_id = body.get("skill_id", "").strip()
    content = body.get("content", "").strip()
    
    if not skill_id or not content:
        return JSONResponse({"error": "skill_id and content are required"}, status_code=400)
        
    try:
        final_id = skills.create_text_skill(skill_id, content, workspace_id)
        return JSONResponse({"success": True, "skill_id": final_id})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

@router.delete("/api/skills/{skill_id}")
async def delete_skill(request: Request, skill_id: str):
    token = _extract_token(request)
    if not token:
        return JSONResponse({"error": "Missing Authorization header"}, status_code=401)
        
    workspace_id = copilot_service._token_key(token) if "copilot" in _SUPPORTED_PROVIDERS and copilot_service else hashlib.sha256(token.encode()).hexdigest()[:16]
    success = skills.delete_user_skill(skill_id, workspace_id)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"error": "Skill not found or could not be deleted"}, status_code=404)
