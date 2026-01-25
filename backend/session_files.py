from pathlib import PurePosixPath

from sandbox_manager import SANDBOX_ROOT, SANDBOX_WORKSPACE

SESSION_FILE_PREFIX_SEPARATOR = "__"


def session_prefix(session_id: str) -> str:
    return f"{session_id}{SESSION_FILE_PREFIX_SEPARATOR}"


def _normalize_base_name(file_path: str) -> str:
    if not file_path:
        return ""
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
    return PurePosixPath(rel_path).name


def session_storage_name(session_id: str, file_name: str) -> str:
    prefix = session_prefix(session_id)
    return file_name if file_name.startswith(prefix) else f"{prefix}{file_name}"


def session_logical_name(session_id: str, file_name: str) -> str:
    prefix = session_prefix(session_id)
    return file_name[len(prefix):] if file_name.startswith(prefix) else file_name


def session_storage_path(session_id: str, file_path: str) -> str:
    base_name = _normalize_base_name(file_path)
    storage_name = session_storage_name(session_id, base_name)
    return f"{SANDBOX_WORKSPACE}/{storage_name}"


def session_logical_path(session_id: str, file_path: str) -> str:
    base_name = _normalize_base_name(file_path)
    return session_logical_name(session_id, base_name)


def is_session_file(session_id: str, file_name: str) -> bool:
    return file_name.startswith(session_prefix(session_id))
