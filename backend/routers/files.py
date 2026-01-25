import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel

# Reuse the same sandbox manager instance as the chat router.
from routers.chat import sandbox_manager, SANDBOX_ROOT
from auth import get_current_user

router = APIRouter(prefix="/files", tags=["files"])


class FileInfo(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified: float


@router.get("/{session_id}/list")
async def list_files(
    session_id: str,
    path: str = "",
    user=Depends(get_current_user),
) -> list[FileInfo]:
    """List files in a session's E2B sandbox directory."""
    sandbox = sandbox_manager.get_sandbox(user["uid"])
    
    if not sandbox:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        target_path = f"{SANDBOX_ROOT}/{path}" if path else SANDBOX_ROOT
        file_list = sandbox.files.list(target_path)
        
        files = []
        for file_info in file_list:
            # E2B file info has name, type attributes
            files.append(FileInfo(
                name=file_info.name,
                path=f"{path}/{file_info.name}" if path else file_info.name,
                is_dir=file_info.type == "dir",
                size=0,  # E2B doesn't provide size in list
                modified=0  # E2B doesn't provide modification time
            ))
        
        # Sort: directories first, then files, alphabetically
        files.sort(key=lambda f: (not f.is_dir, f.name.lower()))
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing files: {str(e)}")


@router.get("/{session_id}/content/{file_path:path}")
async def get_file(
    session_id: str,
    file_path: str,
    user=Depends(get_current_user),
):
    """Get a file's content from a session's E2B sandbox."""
    sandbox = sandbox_manager.get_sandbox(user["uid"])
    
    if not sandbox:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        # Read file from E2B sandbox
        if file_path.startswith("/"):
            target_path = file_path
        else:
            target_path = f"{SANDBOX_ROOT}/{file_path}"
        content = sandbox.files.read(target_path)
        
        # Determine content type based on extension
        ext = Path(file_path).suffix.lower()
        content_types = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".json": "application/json",
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".jsx": "text/plain",
            ".ts": "text/plain",
            ".tsx": "text/plain",
            ".py": "text/x-python",
        }
        
        media_type = content_types.get(ext, "application/octet-stream")
        
        # Return file content as response
        return Response(
            content=content.encode() if isinstance(content, str) else content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={Path(file_path).name}"}
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found: {str(e)}")
