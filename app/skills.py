import os
import shutil
import tempfile
import yaml
import zipfile
import uuid

# Base storage paths
STORAGE_ROOT = os.path.join(tempfile.gettempdir(), "infra-agent-skills")
BUNDLED_SKILLS_DIR = os.path.join(STORAGE_ROOT, "bundled")
USER_SKILLS_DIR = os.path.join(STORAGE_ROOT, "user-uploaded")
ACTIVE_SKILLS_DIR = os.path.join(STORAGE_ROOT, "active")

def init_skills_storage():
    os.makedirs(BUNDLED_SKILLS_DIR, exist_ok=True)
    os.makedirs(USER_SKILLS_DIR, exist_ok=True)
    os.makedirs(ACTIVE_SKILLS_DIR, exist_ok=True)
    
    # Pre-populate bundled skills if they exist in source
    src_bundled = os.path.abspath(os.path.join(os.path.dirname(__file__), "skills", "bundled"))
    if os.path.exists(src_bundled):
        for item in os.listdir(src_bundled):
            src_path = os.path.join(src_bundled, item)
            dst_path = os.path.join(BUNDLED_SKILLS_DIR, item)
            if not os.path.exists(dst_path):
                shutil.copytree(src_path, dst_path)

def list_skills(workspace_id: str) -> dict:
    """Return categorized list of skills for a given user workspace."""
    bundled = []
    if os.path.exists(BUNDLED_SKILLS_DIR):
        for d in os.listdir(BUNDLED_SKILLS_DIR):
            metadata = _read_skill_metadata(os.path.join(BUNDLED_SKILLS_DIR, d))
            if metadata:
                bundled.append(metadata)

    user_uploaded = []
    user_dir = os.path.join(USER_SKILLS_DIR, workspace_id)
    if os.path.exists(user_dir):
        for d in os.listdir(user_dir):
            metadata = _read_skill_metadata(os.path.join(user_dir, d))
            if metadata:
                user_uploaded.append(metadata)

    return {"bundled": bundled, "user_uploaded": user_uploaded}

def _read_skill_metadata(skill_dir: str) -> dict | None:
    # Try reading skill.yaml for metadata
    yaml_path = os.path.join(skill_dir, "skill.yaml")
    if os.path.exists(yaml_path):
        with open(yaml_path, "r", encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
                data["id"] = os.path.basename(skill_dir)
                return data
            except Exception:
                pass
                
    # Fallback: parse SKILL.md for frontmatter
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    if os.path.exists(skill_md_path):
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        data = yaml.safe_load(parts[1])
                        if isinstance(data, dict):
                            data["id"] = os.path.basename(skill_dir)
                            return data
                    except Exception:
                        pass
                        
    # Last resort fallback if just SKILL.md exists without frontmatter
    if os.path.exists(skill_md_path):
        return {"id": os.path.basename(skill_dir), "name": os.path.basename(skill_dir)}
        
    return None

def extract_uploaded_skill(zip_path: str, workspace_id: str) -> str:
    """Extract zip and return the skill id. Attempts to use root directory name."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(tmp_dir)
            
        items = os.listdir(tmp_dir)
        if len(items) == 1 and os.path.isdir(os.path.join(tmp_dir, items[0])):
            # Single top-level directory (e.g. code-reviewer/)
            skill_id = items[0]
            src_dir = os.path.join(tmp_dir, skill_id)
        else:
            # Files at root
            skill_id = f"skill-{uuid.uuid4().hex[:8]}"
            src_dir = tmp_dir
            
        dest_dir = os.path.join(USER_SKILLS_DIR, workspace_id, skill_id)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.copytree(src_dir, dest_dir)
        
    return skill_id

def create_text_skill(skill_id: str, content: str, workspace_id: str) -> str:
    # sanitize skill_id
    safe_id = "".join(c for c in skill_id if c.isalnum() or c in "-_").strip("-")
    if not safe_id:
        safe_id = f"skill-{uuid.uuid4().hex[:8]}"
        
    dest_dir = os.path.join(USER_SKILLS_DIR, workspace_id, safe_id)
    os.makedirs(dest_dir, exist_ok=True)
    
    with open(os.path.join(dest_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(content)
        
    return safe_id

def delete_user_skill(skill_id: str, workspace_id: str) -> bool:
    target = os.path.join(USER_SKILLS_DIR, workspace_id, skill_id)
    if os.path.exists(target):
        shutil.rmtree(target)
        return True
    return False

def compile_active_skills(enabled_skill_ids: list[str], workspace_id: str, session_id: str) -> str:
    """
    Creates an ephemeral flat directory structure for the active SDK session.
    e.g. /tmp/.../active/<session_id>/skills/<skill_id>/
    Returns the parent directory (which contains the 'skills' folder).
    """
    session_parent_dir = os.path.join(ACTIVE_SKILLS_DIR, session_id)
    session_active_dir = os.path.join(session_parent_dir, "skills")
    
    if os.path.exists(session_active_dir):
        shutil.rmtree(session_active_dir)
    os.makedirs(session_active_dir, exist_ok=True)
    
    for skill_id in enabled_skill_ids:
        # Search in bundled first
        src = os.path.join(BUNDLED_SKILLS_DIR, skill_id)
        if not os.path.exists(src):
            # Fallback to user workspace
            src = os.path.join(USER_SKILLS_DIR, workspace_id, skill_id)
            
        if os.path.exists(src):
            dst = os.path.join(session_active_dir, skill_id)
            try:
                shutil.copytree(src, dst)
            except Exception:
                pass
                
    # Create .claude/skills symlink for Claude SDK native discovery
    claude_dir = os.path.join(session_parent_dir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    claude_skills_symlink = os.path.join(claude_dir, "skills")
    
    if os.path.lexists(claude_skills_symlink):
        if os.path.islink(claude_skills_symlink):
            os.unlink(claude_skills_symlink)
        else:
            shutil.rmtree(claude_skills_symlink)
            
    try:
        os.symlink(session_active_dir, claude_skills_symlink, target_is_directory=True)
    except OSError:
        shutil.copytree(session_active_dir, claude_skills_symlink)
        
    # Create .codex/skills symlink for Codex SDK native discovery
    codex_dir = os.path.join(session_parent_dir, ".codex")
    os.makedirs(codex_dir, exist_ok=True)
    codex_skills_symlink = os.path.join(codex_dir, "skills")
    
    if os.path.lexists(codex_skills_symlink):
        if os.path.islink(codex_skills_symlink):
            os.unlink(codex_skills_symlink)
        else:
            shutil.rmtree(codex_skills_symlink)
            
    try:
        os.symlink(session_active_dir, codex_skills_symlink, target_is_directory=True)
    except OSError:
        shutil.copytree(session_active_dir, codex_skills_symlink)
                
    return session_parent_dir

init_skills_storage()
