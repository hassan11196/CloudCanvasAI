from pathlib import PurePosixPath

from sandbox_manager import SANDBOX_ROOT, SANDBOX_WORKSPACE

SESSION_FILE_PREFIX_SEPARATOR = "__"


def session_prefix(session_id: str) -> str:
    """Legacy prefix used for backward compatibility with pre-folder storage."""
    return f"{session_id}{SESSION_FILE_PREFIX_SEPARATOR}"


def session_workspace_dir(session_id: str) -> str:
    """Workspace directory reserved for the session."""
    return f"{SANDBOX_WORKSPACE}/{session_id}"


def _normalize_relative_path(file_path: str) -> PurePosixPath:
    """Normalize user-supplied paths to a safe, workspace-relative path."""
    if not file_path:
        return PurePosixPath("")

    posix_path = PurePosixPath(file_path)
    if posix_path.is_absolute():
        try:
            posix_path = posix_path.relative_to(PurePosixPath(SANDBOX_ROOT))
        except ValueError:
            posix_path = PurePosixPath(posix_path.name)

    rel_path = posix_path.as_posix().lstrip("/")
    if rel_path.startswith("workspace/"):
        rel_path = rel_path[len("workspace/"):]
    elif rel_path.startswith("tmp/"):
        rel_path = rel_path[len("tmp/"):]

    safe_parts = [part for part in PurePosixPath(rel_path).parts if part not in (".", "..")]
    return PurePosixPath(*safe_parts)


def session_storage_path(session_id: str, file_path: str) -> str:
    """Full sandbox path for a file inside the session workspace folder."""
    normalized = _normalize_relative_path(file_path)
    parts = normalized.parts
    if parts and parts[0] == session_id:
        normalized = PurePosixPath(*parts[1:]) if len(parts) > 1 else PurePosixPath("")

    legacy_prefix = session_prefix(session_id)
    if normalized.name.startswith(legacy_prefix):
        normalized = normalized.with_name(normalized.name[len(legacy_prefix):])

    if not normalized.as_posix():
        raise ValueError("file_path is required")
    return f"{session_workspace_dir(session_id)}/{normalized.as_posix()}"


def session_logical_path(session_id: str, file_path: str) -> str:
    """
    Path to show in the UI (no session identifiers).

    Accepts either folder-based paths (session_id/.../file.ext) or legacy
    prefixed filenames and strips any session-specific markers.
    """
    normalized = _normalize_relative_path(file_path)
    parts = normalized.parts
    if parts and parts[0] == session_id:
        normalized = PurePosixPath(*parts[1:]) if len(parts) > 1 else PurePosixPath("")

    name = normalized.name
    legacy_prefix = session_prefix(session_id)
    if name.startswith(legacy_prefix):
        stripped = name[len(legacy_prefix):]
        normalized = normalized.with_name(stripped)

    return normalized.as_posix()


def session_logical_name(session_id: str, file_path: str) -> str:
    """File name without session identifier, discarding any parent folders."""
    logical_path = session_logical_path(session_id, file_path)
    return PurePosixPath(logical_path).name


def is_session_file(session_id: str, file_path: str) -> bool:
    """
    Determine whether a file belongs to the session.

    Supports both folder-based storage (session_id/...) and the legacy
    filename prefix format.
    """
    normalized = _normalize_relative_path(file_path)
    parts = normalized.parts
    if parts and parts[0] == session_id:
        return True
    return normalized.name.startswith(session_prefix(session_id))
