from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel

# Reuse the same sandbox manager instance as the chat router.
from routers.chat import sandbox_manager
from sandbox_manager import SANDBOX_WORKSPACE
from session_files import (
    is_session_file,
    session_logical_name,
    session_logical_path,
    session_prefix,
    session_storage_path,
    session_workspace_dir,
)
from auth import get_current_user

router = APIRouter(prefix="/files", tags=["files"])

ARTIFACT_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".pdf", ".md", ".txt"}


class FileInfo(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified: float


def _is_artifact(path: str) -> bool:
    """Only expose user-facing document artifacts."""
    return Path(path).suffix.lower() in ARTIFACT_EXTENSIONS


def _iter_sandbox_files(sandbox, root_path: str) -> list[tuple[str, bool, object]]:
    results: list[tuple[str, bool, object]] = []
    stack: list[tuple[str, str]] = [(root_path, "")]
    while stack:
        abs_dir, rel_prefix = stack.pop()
        for entry in sandbox.files.list(abs_dir):
            rel_path = f"{rel_prefix}/{entry.name}".lstrip("/")
            if entry.type == "dir":
                stack.append((f"{abs_dir}/{entry.name}", rel_path))
                results.append((rel_path, True, entry))
            else:
                results.append((rel_path, False, entry))
    return results


@router.get("/{session_id}/list")
async def list_files(
    session_id: str,
    path: str = "",
    user=Depends(get_current_user),
) -> list[FileInfo]:
    """List files generated in this session's workspace."""
    sandbox = sandbox_manager.get_sandbox(user["uid"])
    
    if not sandbox:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        if path:
            raise HTTPException(status_code=400, detail="Path listing is not supported for session files")
        session_dir = session_workspace_dir(session_id)
        try:
            sandbox.files.make_dir(session_dir)
        except Exception:
            pass

        files = []

        # Prefer folder-based storage (recursive)
        try:
            session_entries = _iter_sandbox_files(sandbox, session_dir)
        except Exception:
            session_entries = []

        seen_paths = set()
        for rel_path, is_dir, file_info in session_entries:
            if is_dir:
                continue
            logical_path = session_logical_path(session_id, f"{session_id}/{rel_path}")
            logical_name = PurePosixPath(logical_path).name
            files.append(FileInfo(
                name=logical_name,
                path=logical_path,
                is_dir=False,
                size=getattr(file_info, "size", 0) or 0,
                modified=getattr(file_info, "modified_at", 0) or 0
            ))
            seen_paths.add(logical_path)

        # Legacy prefixed files fallback
        try:
            legacy_list = sandbox.files.list(SANDBOX_WORKSPACE)
        except Exception:
            legacy_list = []

        for file_info in legacy_list:
            if file_info.type == "dir":
                continue
            if not is_session_file(session_id, file_info.name):
                continue
            logical_name = session_logical_name(session_id, file_info.name)
            if logical_name in seen_paths:
                continue
            files.append(FileInfo(
                name=logical_name,
                path=logical_name,
                is_dir=False,
                size=getattr(file_info, "size", 0) or 0,
                modified=getattr(file_info, "modified_at", 0) or 0
            ))
        
        # Sort: directories first, then files, alphabetically
        files.sort(key=lambda f: (not f.is_dir, f.name.lower()))
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing files: {str(e)}")


@router.get("/{session_id}/artifacts")
async def list_artifacts(
    session_id: str,
    user=Depends(get_current_user),
) -> list[FileInfo]:
    """List user-facing document artifacts for this session."""
    sandbox = sandbox_manager.get_sandbox(user["uid"])

    if not sandbox:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        session_dir = session_workspace_dir(session_id)
        try:
            sandbox.files.make_dir(session_dir)
        except Exception:
            pass

        artifacts: list[FileInfo] = []
        try:
            session_entries = _iter_sandbox_files(sandbox, session_dir)
        except Exception:
            session_entries = []

        seen_paths = set()
        for rel_path, is_dir, file_info in session_entries:
            if is_dir:
                continue
            if not _is_artifact(rel_path):
                continue

            logical_path = session_logical_path(session_id, f"{session_id}/{rel_path}")
            logical_name = PurePosixPath(logical_path).name
            artifacts.append(FileInfo(
                name=logical_name,
                path=logical_path,
                is_dir=False,
                size=getattr(file_info, "size", 0) or 0,
                modified=getattr(file_info, "modified_at", 0) or 0
            ))
            seen_paths.add(logical_path)

        # Legacy prefixed files fallback
        try:
            legacy_list = sandbox.files.list(SANDBOX_WORKSPACE)
        except Exception:
            legacy_list = []

        for file_info in legacy_list:
            if file_info.type == "dir":
                continue
            if not _is_artifact(file_info.name):
                continue
            if not is_session_file(session_id, file_info.name):
                continue
            logical_name = session_logical_name(session_id, file_info.name)
            if logical_name in seen_paths:
                continue
            artifacts.append(FileInfo(
                name=logical_name,
                path=logical_name,
                is_dir=False,
                size=getattr(file_info, "size", 0) or 0,
                modified=getattr(file_info, "modified_at", 0) or 0
            ))

        # Newest first, then name
        artifacts.sort(key=lambda f: (-f.modified, f.name.lower()))
        return artifacts
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing artifacts: {str(e)}")


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
        target_path = session_storage_path(session_id, file_path)
        content = None

        # Determine if file is binary based on extension
        ext = Path(file_path).suffix.lower()
        binary_extensions = {'.docx', '.pptx', '.xlsx', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.zip'}
        is_binary = ext in binary_extensions

        # CRITICAL: Use format="bytes" for binary files to prevent corruption
        # E2B's default format="text" decodes binary as UTF-8, corrupting the data
        read_format = "bytes" if is_binary else "text"

        # Try primary path first
        try:
            content = sandbox.files.read(target_path, format=read_format)
        except Exception:
            # Try legacy path as fallback
            legacy_name = f"{session_prefix(session_id)}{session_logical_name(session_id, file_path)}"
            legacy_path = f"{SANDBOX_WORKSPACE}/{legacy_name}"
            try:
                content = sandbox.files.read(legacy_path, format=read_format)
            except Exception:
                raise HTTPException(
                    status_code=404,
                    detail=f"File not found at {target_path} or {legacy_path}"
                )

        # Validate content is not empty
        if content is None:
            raise HTTPException(status_code=404, detail="File content is empty")

        # Convert to bytes for response
        if isinstance(content, (bytes, bytearray)):
            content_bytes = bytes(content)
        elif isinstance(content, str):
            content_bytes = content.encode('utf-8')
        else:
            content_bytes = bytes(content)

        # Validate binary files have minimum size
        if is_binary and len(content_bytes) < 100:
            raise HTTPException(
                status_code=404,
                detail=f"File appears to be incomplete ({len(content_bytes)} bytes). It may still be generating."
            )

        # Determine content type based on extension
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
            content=content_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={Path(file_path).name}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Error reading file: {str(e)}")
