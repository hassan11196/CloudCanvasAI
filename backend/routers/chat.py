import json
import os
import time
import uuid
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Optional, Any
import re
import traceback
import logging
import shutil

from dotenv import load_dotenv
from fastapi import APIRouter, Depends

load_dotenv()
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from claude_agent_sdk import (
    query,
    tool,
    create_sdk_mcp_server,
    ClaudeAgentOptions,
    AssistantMessage,
    SystemMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from sandbox_manager import SandboxManager, SANDBOX_ROOT, SANDBOX_WORKSPACE
from session_files import (
    session_storage_path,
    session_logical_path,
    session_workspace_dir,
    is_session_file,
)
from auth import get_current_user

# Document-focused tools for the skills integration
DOCUMENT_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]

# File extensions that trigger document preview
DOCUMENT_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".pdf", ".md", ".txt", ".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".py"}

# Path to the docx creation script
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _ensure_host_skills_available() -> None:
    """
    Make sure the host agent (outside the E2B sandbox) has access to the bundled skills.
    If /etc/claude-code/.claude/skills is missing, seed it from the repo copy; also set env fallbacks.
    """
    managed_dir = Path("/etc/claude-code/.claude/skills")
    user_dir = Path.home() / ".claude/skills"
    project_skills = SKILLS_DIR

    # Skip if we don't have bundled skills to copy
    if not project_skills.exists():
        logger.warning("Project skills directory not found at %s", project_skills)
        return

    for target in (managed_dir, user_dir):
        try:
            target.mkdir(parents=True, exist_ok=True)
            # Copy per-skill folder only if it is missing to avoid clobbering updates
            for skill in project_skills.iterdir():
                dest = target / skill.name
                if dest.exists():
                    continue
                if skill.is_dir():
                    shutil.copytree(skill, dest)
                else:
                    shutil.copy2(skill, dest)
        except Exception as exc:
            print.warning("Unable to prepare skills in %s: %s", target, exc)

    # Ensure the agent looks at the bundled skills even if managed dir prep fails
    os.environ.setdefault("CLAUDE_PROJECT_DIR", str(Path(__file__).parent.parent))
    os.environ.setdefault("CLAUDE_SKILLS_DIRS", str(project_skills))


# Prepare host skills on import so server-side agent startups don't fail on missing paths
try:
    _ensure_host_skills_available()
except Exception as e:
    print("Error ensuring host skills availability: %s", e)
# System prompt for document creation capabilities
DOCUMENT_SYSTEM_PROMPT = """
You are Zephior Canvas, an AI assistant with document creation and edit capabilities.
"""
SKILL_NAMES = ("docx", "pdf", "pptx", "xlsx")
SKILL_PATH_NOTE = (
    "Skill assets are available under /home/user/workspace/skills/{docx,pdf,pptx,xlsx}. "
    "When instructions reference relative paths like ooxml/scripts or scripts/thumbnail.py, "
    "run them from the appropriate skill directory or use absolute paths under /home/user/workspace/skills. "
    "Use /home/user/workspace for working files and /home/user/tmp for temporary files."

)

FILE_KEYWORDS = {
    ".docx",
    ".pptx",
    ".xlsx",
    ".pdf",
    "docx",
    "pptx",
    "xlsx",
    "pdf",
    "word",
    "powerpoint",
    "excel",
    "slide",
    "slides",
    "presentation",
    "spreadsheet",
    "document",
    "resume",
    "template",
    "proposal",
    "report",
    "deck",
}

DOC_NAME_PATTERN = re.compile(r"([\w.-]+\.(?:docx|pptx|xlsx|pdf))", re.IGNORECASE)
DOC_REQUEST_TRIGGERS = ("create", "generate", "make", "draft", "write", "build", "produce")


def should_use_sandbox(message: str) -> bool:
    lowered = message.lower()
    if any(ext in lowered for ext in (".docx", ".pptx", ".xlsx", ".pdf")):
        return True
    for keyword in FILE_KEYWORDS:
        if keyword in lowered:
            return True
    return False


def extract_requested_doc_name(message: str) -> Optional[str]:
    match = DOC_NAME_PATTERN.search(message)
    if match:
        return match.group(1)
    return None


def is_doc_generation_request(message: str) -> bool:
    lowered = message.lower()
    if not should_use_sandbox(lowered):
        return False
    return any(trigger in lowered for trigger in DOC_REQUEST_TRIGGERS)

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize E2B sandbox manager
sandbox_manager = SandboxManager()
SESSION_USAGE: dict[str, dict[str, Any]] = {}
SESSION_USERS: dict[str, str] = {}


def get_or_create_session(
    user_id: str,
    session_id: Optional[str] = None,
) -> tuple[str, object]:
    """Get existing session or create new one with isolated E2B sandbox."""
    start_time = time.monotonic()
    print("[stream] get_or_create_session start user_id=%s session_id=%s" % (user_id, session_id))
    if session_id:
        sandbox = sandbox_manager.get_sandbox(user_id)
        if sandbox:
            print(
                "[stream] reuse sandbox duration=%.3fs sandbox_id=%s",
                time.monotonic() - start_time,
                getattr(sandbox, "sandbox_id", "unknown"),
            )
            return session_id, sandbox

        sandbox = sandbox_manager.create_sandbox(user_id)
        print(
            "[stream] created sandbox for session duration=%.3fs sandbox_id=%s",
            time.monotonic() - start_time,
            getattr(sandbox, "sandbox_id", "unknown"),
        )
        return session_id, sandbox

    # Create new session with E2B sandbox
    new_id = str(uuid.uuid4())

    sandbox = sandbox_manager.create_sandbox(user_id)
    print(
        "[stream] created sandbox new session duration=%.3fs sandbox_id=%s",
        time.monotonic() - start_time,
        getattr(sandbox, "sandbox_id", "unknown"),
    )
    return new_id, sandbox


class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None


def get_file_path_from_tool(tool_name: str, tool_input: dict) -> Optional[str]:
    """Extract file path from Write, Edit, or Bash tool input."""
    import re
    import shlex

    if tool_name in ("Write", "Edit", "write_to_file", "replace_file_content", "multi_replace_file_content"):
        return tool_input.get("file_path") or tool_input.get("TargetFile") or tool_input.get("path")
    elif tool_name in ("Bash", "run_command"):
        command = tool_input.get("command") or tool_input.get("CommandLine") or ""

        # Try to extract document files from command
        # Match quoted paths: "path/file.docx" or 'path/file.docx'
        quoted_match = re.search(r'''["']([^"']*\.(?:docx|pptx|xlsx|pdf))["']''', command)
        if quoted_match:
            return quoted_match.group(1)

        # Match unquoted paths, but more carefully
        # Look for word boundaries and path-like strings
        unquoted_match = re.search(r'(?:^|\s)([./\w-]+\.(?:docx|pptx|xlsx|pdf))(?:\s|$)', command)
        if unquoted_match:
            path = unquoted_match.group(1)
            # Filter out common false positives like flags
            if not path.startswith('-'):
                return path

        # Special handling for create_docx.py - first argument is usually the output
        if "create_docx.py" in command:
            try:
                # Use shlex to properly parse the command
                parts = shlex.split(command)
                # Find index of create_docx.py
                idx = next((i for i, p in enumerate(parts) if "create_docx.py" in p), None)
                if idx is not None and idx + 1 < len(parts):
                    # Next argument is typically the output file
                    potential_path = parts[idx + 1]
                    if potential_path.endswith(('.docx', '.pptx', '.xlsx', '.pdf')):
                        return potential_path
            except ValueError:
                # shlex.split can fail on malformed commands, fall back to regex
                pass

    return None


def scan_for_new_documents(sandbox, known_files: set, session_id: str) -> list[str]:
    """Scan E2B sandbox for new document files in the session workspace."""
    new_files = []
    scan_dir = session_workspace_dir(session_id)
    try:
        entries = _iter_sandbox_files(sandbox, scan_dir, base_root=SANDBOX_WORKSPACE)
        for rel_path, is_dir in entries:
            if is_dir:
                continue
            if not is_session_file(session_id, rel_path):
                continue
            logical_name = session_logical_path(session_id, rel_path)
            if not logical_name:
                continue
            if not any(logical_name.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
                continue
            if logical_name not in known_files:
                new_files.append(logical_name)
                known_files.add(logical_name)
    except Exception:
        # Directory might not exist yet, that's okay
        pass

    return new_files


def scan_for_new_documents_global(sandbox, known_files: set, session_id: str) -> list[str]:
    """Fallback scan for document files outside the session workspace."""
    new_files = []
    scan_dir = SANDBOX_WORKSPACE
    try:
        entries = _iter_sandbox_files(sandbox, scan_dir, base_root=SANDBOX_ROOT)
        for rel_path, is_dir in entries:
            if is_dir:
                continue
            if not any(rel_path.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
                continue
            logical_path = _ensure_session_copy(sandbox, session_id, f"{SANDBOX_ROOT}/{rel_path}")
            if not logical_path:
                continue
            if logical_path not in known_files:
                new_files.append(logical_path)
                known_files.add(logical_path)
    except Exception:
        pass

    return new_files


def is_document_file(file_path: str) -> bool:
    """Check if file is a document type we want to preview."""
    if not file_path:
        return False
    ext = Path(file_path).suffix.lower()
    return ext in DOCUMENT_EXTENSIONS


def validate_file_in_sandbox(sandbox, file_path: str, min_size: int = 100) -> bool:
    """
    Validate that a file exists in the sandbox and has meaningful content.

    Args:
        sandbox: E2B sandbox instance
        file_path: Full path to the file in sandbox
        min_size: Minimum file size in bytes to consider valid (default 100 for docx)

    Returns:
        True if file exists and has content >= min_size, False otherwise
    """
    if not sandbox or not file_path:
        return False

    try:
        # Determine if file is binary based on extension
        ext = Path(file_path).suffix.lower()
        binary_extensions = {'.docx', '.pptx', '.xlsx', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.zip'}
        is_binary = ext in binary_extensions

        # CRITICAL: Use format="bytes" for binary files to get accurate size
        # and prevent UTF-8 decoding issues
        read_format = "bytes" if is_binary else "text"

        content = sandbox.files.read(file_path, format=read_format)
        if content is None:
            return False

        # Get byte length
        if isinstance(content, (bytes, bytearray)):
            size = len(content)
        elif isinstance(content, str):
            size = len(content.encode('utf-8'))
        else:
            return False

        return size >= min_size
    except Exception as e:
        logger.debug(f"File validation failed for {file_path}: {e}")
        return False


def _extract_tool_path(tool_input: dict) -> Optional[str]:
    """Extract file_path from tool input, supporting legacy parameter names."""
    return tool_input.get("file_path") or tool_input.get("path")


def _resolve_sandbox_path(path: Optional[str]) -> str:
    if not path:
        return SANDBOX_ROOT
    posix_path = PurePosixPath(path)
    if posix_path.is_absolute():
        resolved = posix_path
    else:
        resolved = PurePosixPath(SANDBOX_ROOT) / posix_path
    if not resolved.is_relative_to(PurePosixPath(SANDBOX_ROOT)):
        raise ValueError("Path escapes sandbox root")
    return str(resolved)


def _ensure_session_copy(sandbox, session_id: str, file_path: str) -> Optional[str]:
    """Ensure a document file is available inside the session workspace folder."""
    if not file_path or not sandbox:
        return None

    posix_path = PurePosixPath(file_path)
    session_dir = PurePosixPath(session_workspace_dir(session_id))

    # If already within session workspace, nothing to do.
    if posix_path.is_absolute():
        try:
            if posix_path.is_relative_to(session_dir):
                return session_logical_path(session_id, file_path)
        except AttributeError:
            if str(posix_path).startswith(str(session_dir)):
                return session_logical_path(session_id, file_path)

    logical_path = session_logical_path(session_id, file_path)
    if not logical_path:
        return None

    target_path = session_storage_path(session_id, logical_path)

    if not posix_path.is_absolute():
        return logical_path

    source_path = str(posix_path)

    if source_path == target_path:
        return logical_path

    # Read the source file (use bytes for binary docs to avoid corruption)
    try:
        ext = posix_path.suffix.lower()
        binary_exts = {'.docx', '.pptx', '.xlsx', '.pdf'}
        read_format = "bytes" if ext in binary_exts else "text"
        content = sandbox.files.read(source_path, format=read_format)
    except Exception:
        return None

    try:
        sandbox.files.make_dir(str(PurePosixPath(target_path).parent))
    except Exception:
        pass

    try:
        sandbox.files.write(target_path, content)
    except Exception:
        return None

    return logical_path


def _iter_sandbox_files(sandbox, root_path: str, base_root: str = SANDBOX_ROOT) -> list[tuple[str, bool]]:
    results: list[tuple[str, bool]] = []
    base_prefix = str(PurePosixPath(root_path).relative_to(PurePosixPath(base_root)))
    if base_prefix == ".":
        base_prefix = ""
    stack: list[tuple[str, str]] = [(root_path, base_prefix)]
    while stack:
        abs_dir, rel_prefix = stack.pop()
        for entry in sandbox.files.list(abs_dir):
            rel_path = f"{rel_prefix}/{entry.name}".lstrip("/")
            if entry.type == "dir":
                stack.append((f"{abs_dir}/{entry.name}", rel_path))
                results.append((rel_path, True))
            else:
                results.append((rel_path, False))
    return results


def _build_sandbox_mcp_server(sandbox, session_id: str):
    read_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read"
            },
        },
        "required": ["file_path"],
    }
    write_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to write"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            },
        },
        "required": ["file_path", "content"],
    }
    edit_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit"
            },
            "content": {
                "type": "string",
                "description": "New content (if replacing entire file)"
            },
            "edits": {
                "type": "array",
                "description": "List of text replacements to apply",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["old_text", "new_text"],
                },
            },
        },
        "required": ["file_path"],
    }
    glob_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files"
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (optional, defaults to sandbox root)"
            },
        },
        "required": ["pattern"],
    }
    grep_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for"
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (optional, defaults to sandbox root)"
            },
        },
        "required": ["pattern"],
    }
    bash_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute"
            },
        },
        "required": ["command"],
    }

    def _ensure_session_dir():
        try:
            sandbox.files.make_dir(session_workspace_dir(session_id))
        except Exception:
            pass

    @tool("Read", "Read a file from the sandbox filesystem", read_schema)
    async def read_tool(args):
        try:
            file_path = _extract_tool_path(args)
            if not file_path:
                raise ValueError("file_path is required")
            try:
                sandbox.files.make_dir(session_workspace_dir(session_id))
            except Exception:
                pass
            content = None
            if not PurePosixPath(file_path).is_absolute():
                session_path = session_storage_path(session_id, file_path)
                try:
                    content = sandbox.files.read(session_path)
                except Exception:
                    content = None
            if content is None:
                target_path = _resolve_sandbox_path(file_path)
                content = sandbox.files.read(target_path)
            if isinstance(content, bytes):
                text = content.decode("utf-8", errors="replace")
            else:
                text = str(content)
            return {"content": [{"type": "text", "text": text}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Read error: {exc}"}],
                "is_error": True,
            }

    @tool("Write", "Write a file to the sandbox filesystem", write_schema)
    async def write_tool(args):
        try:
            file_path = _extract_tool_path(args)
            if not file_path:
                raise ValueError("file_path is required")
            _ensure_session_dir()
            target_path = session_storage_path(session_id, file_path)
            target_parent = PurePosixPath(target_path).parent
            try:
                sandbox.files.make_dir(str(target_parent))
            except Exception:
                pass
            content = args.get("content", "")
            sandbox.files.write(target_path, content)
            return {"content": [{"type": "text", "text": f"Wrote {target_path}"}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Write error: {exc}"}],
                "is_error": True,
            }

    @tool("Edit", "Edit a file in the sandbox filesystem", edit_schema)
    async def edit_tool(args):
        try:
            file_path = _extract_tool_path(args)
            if not file_path:
                raise ValueError("file_path is required")
            _ensure_session_dir()
            target_path = session_storage_path(session_id, file_path)
            content = sandbox.files.read(target_path)
            if isinstance(content, bytes):
                text = content.decode("utf-8", errors="replace")
            else:
                text = str(content)

            if "content" in args and not args.get("edits"):
                updated = args.get("content", "")
            else:
                updated = text
                edits = args.get("edits") or []
                for edit in edits:
                    old = edit.get("old_text", "")
                    new = edit.get("new_text", "")
                    if old not in updated:
                        return {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Edit error: old_text not found in {target_path}",
                                }
                            ],
                            "is_error": True,
                        }
                    updated = updated.replace(old, new, 1)

            sandbox.files.write(target_path, updated)
            return {"content": [{"type": "text", "text": f"Edited {target_path}"}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Edit error: {exc}"}],
                "is_error": True,
            }

    @tool("Glob", "List files in the sandbox matching a glob pattern", glob_schema)
    async def glob_tool(args):
        try:
            pattern = args.get("pattern") or "*"
            base_path = _resolve_sandbox_path(args.get("path"))
            entries = _iter_sandbox_files(sandbox, base_path)
            matches = [
                path for path, is_dir in entries if not is_dir and fnmatch(path, pattern)
            ]
            return {"content": [{"type": "text", "text": "\n".join(matches)}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Glob error: {exc}"}],
                "is_error": True,
            }

    @tool("Grep", "Search file contents in the sandbox", grep_schema)
    async def grep_tool(args):
        try:
            pattern = args.get("pattern") or ""
            if not pattern:
                return {"content": [{"type": "text", "text": ""}]}
            base_path = _resolve_sandbox_path(args.get("path"))
            matcher = re.compile(pattern)
            entries = _iter_sandbox_files(sandbox, base_path)
            results = []
            for rel_path, is_dir in entries:
                if is_dir:
                    continue
                abs_path = _resolve_sandbox_path(rel_path)
                try:
                    content = sandbox.files.read(abs_path)
                except Exception:
                    continue
                if isinstance(content, bytes):
                    text = content.decode("utf-8", errors="replace")
                else:
                    text = str(content)
                for idx, line in enumerate(text.splitlines(), start=1):
                    if matcher.search(line):
                        results.append(f"{rel_path}:{idx}:{line}")
                        if len(results) >= 200:
                            break
                if len(results) >= 200:
                    break
            return {"content": [{"type": "text", "text": "\n".join(results)}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Grep error: {exc}"}],
                "is_error": True,
            }

    @tool("Bash", "Run a command in the sandbox shell", bash_schema)
    async def bash_tool(args):
        try:
            command = args.get("command", "")
            if not command:
                return {"content": [{"type": "text", "text": "(no command provided)"}]}

            _ensure_session_dir()
            # Use E2B's native command execution
            result = sandbox.commands.run(
                command,
                timeout=120,
                cwd=session_workspace_dir(session_id),
                envs={
                    "TMPDIR": f"{SANDBOX_ROOT}/tmp",
                    "NODE_PATH": "/usr/local/lib/node_modules",
                },
            )

            # Build output from stdout and stderr
            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(result.stderr)

            output = "\n".join(output_parts) if output_parts else "(no output)"

            # Include exit code if non-zero and no stderr
            if result.exit_code != 0 and not result.stderr:
                output = f"Exit code: {result.exit_code}\n{output}"

            # Include error if present
            if result.error:
                output = f"Error: {result.error}\n{output}"

            return {"content": [{"type": "text", "text": output}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Bash error: {exc}"}],
                "is_error": True,
            }

    return create_sdk_mcp_server(
        "sandbox",
        tools=[read_tool, write_tool, edit_tool, glob_tool, grep_tool, bash_tool],
    )


async def agent_event_generator(
    message: str,
    user_id: str,
    session_id: Optional[str] = None,
):
    """Generate SSE events from Claude agent execution."""
    # All requests must run inside the E2B sandbox; disable host-only execution paths
    use_sandbox = True
    sandbox = None
    existing_sandbox = sandbox_manager.get_sandbox(user_id) if session_id else None

    if existing_sandbox:
        sandbox = existing_sandbox
        sid = session_id or str(uuid.uuid4())
        is_resume = True
        SESSION_USERS[sid] = user_id
        yield f"data: {json.dumps({'type': 'status', 'content': 'Resuming sandbox'})}\n\n"
    else:
        yield f"data: {json.dumps({'type': 'status', 'content': 'Starting sandbox'})}\n\n"
        print("[stream] sandbox requested user_id=%s session_id=%s", user_id, session_id)
        sid, sandbox = get_or_create_session(user_id, session_id)
        is_resume = session_id is not None
        SESSION_USERS[sid] = user_id

    doc_generation_announced: set[str] = set()
    doc_intent = use_sandbox and is_doc_generation_request(message)
    files_emitted = False

    yield f"data: {json.dumps({'type': 'session', 'session_id': sid})}\n\n"
    yield f"data: {json.dumps({'type': 'status', 'content': 'Preparing agent'})}\n\n"

    if use_sandbox and is_doc_generation_request(message):
        requested_name = extract_requested_doc_name(message)
        status_event = {
            "type": "status",
            "content": "doc_generation_requested",
        }
        if requested_name:
            status_event["path"] = requested_name
            doc_generation_announced.add(requested_name)
        yield f"data: {json.dumps(status_event)}\n\n"

    # Load system prompt from SKILL.md if available
    skill_prompt = DOCUMENT_SYSTEM_PROMPT.strip()
    skill_prompt += "\n\n" + SKILL_PATH_NOTE
    skills_dir = Path(__file__).parent.parent / "skills"
    for skill_name in SKILL_NAMES:
        skill_md_path = skills_dir / skill_name / "SKILL.md"
        if skill_md_path.exists():
            skill_prompt += f"\n\n# Skill: {skill_name}\n" + skill_md_path.read_text()

    # Build system prompt with E2B paths
    # Only need to replace the scripts path since skills path is already correct
    system_prompt = skill_prompt.replace(
        "/scripts/create_docx.py",
        f"{SANDBOX_ROOT}/scripts/create_docx.py"
    )
    system_prompt += (
        f"\n\nSession file rule: store generated files in {session_workspace_dir(sid)} "
        "without including the session ID in filenames. Create the session folder if needed."
        "\nWhen starting document creation, emit a status update labelled 'doc_generation_requested' along with the intended document name."
        "\nAlways create files directly using the sandbox tools (Write/Edit/Bash) without asking for permission. "
        "If a tool call fails, retry once using python-docx via Bash and ensure the output is saved under the session workspace folder."
    )
    print(f"[stream] system prompt prepared, length={len(system_prompt)}")
    sandbox_server = _build_sandbox_mcp_server(sandbox, sid) if sandbox else None
    stderr_lines: list[str] = []

    def _stderr_callback(line: str) -> None:
        stderr_lines.append(line)
        print(f"STDERR: {line}")
        
    print(f"[stream] building agent options for session {sid}, is_resume={is_resume}")
    options = ClaudeAgentOptions(
        tools=[],
        allowed_tools=DOCUMENT_TOOLS,
        permission_mode="bypassPermissions",
        cwd=None,
        resume=sid if is_resume else None,
        continue_conversation=is_resume,
        system_prompt=system_prompt,
        mcp_servers={"sandbox": sandbox_server} if sandbox_server else {},
        stderr=_stderr_callback,
        # extra_args={"debug-to-stderr": None},
    )

    print(f"[stream] starting agent query for session {sid}, doc_intent={doc_intent}")
    async def _prompt_stream():
        yield {
            "type": "user",
            "message": {"role": "user", "content": message},
            "parent_tool_use_id": None,
            "session_id": sid,
        }

    # Track pending tool uses by ID
    pending_tool_uses = {}
    known_files = set()
    print(f"[stream] initial known files: {known_files}")
    # Get initial file list from E2B sandbox
    if sandbox:
        try:
            try:
                sandbox.files.make_dir(session_workspace_dir(sid))
            except Exception:
                pass

            entries = _iter_sandbox_files(
                sandbox,
                session_workspace_dir(sid),
                base_root=SANDBOX_WORKSPACE,
            )
            for rel_path, is_dir in entries:
                if is_dir:
                    continue
                if not is_session_file(sid, rel_path):
                    continue
                logical_path = session_logical_path(sid, rel_path)
                if any(logical_path.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
                    known_files.add(logical_path)
        except Exception as e:
            print(f"Error listing initial files: {e}")
    print(f"[stream] populated known files: {known_files}")
    try:
        async for msg in query(prompt=_prompt_stream(), options=options):
            print(f"[stream] received agent message of type {type(msg)}")
            if isinstance(msg, AssistantMessage):
                print(f"DEBUG: AssistantMessage with {len(msg.content)} blocks")
                for block in msg.content:
                    if isinstance(block, ThinkingBlock):
                        event = {'type': 'thinking', 'content': block.thinking}
                        print(f"DEBUG: ThinkingBlock: {block.thinking}")
                        yield f"data: {json.dumps(event)}\n\n"
                    elif isinstance(block, ToolUseBlock):
                        # Store tool use by ID
                        pending_tool_uses[block.id] = {
                            'name': block.name,
                            'input': block.input
                        }

                        file_path = get_file_path_from_tool(block.name, block.input)
                        if file_path and is_document_file(file_path):
                            logical_path = session_logical_path(sid, file_path)
                            if logical_path and logical_path not in doc_generation_announced:
                                doc_generation_announced.add(logical_path)
                                status_event = {
                                    'type': 'status',
                                    'content': 'doc_generation_requested',
                                    'path': logical_path,
                                }
                                yield f"data: {json.dumps(status_event)}\n\n"

                        event = {
                            'type': 'tool_use',
                            'tool_name': block.name,
                            'tool_input': block.input
                        }
                        print(f"DEBUG: ToolUseBlock: {block.name} with input {block.input}")
                        yield f"data: {json.dumps(event)}\n\n"
                    elif isinstance(block, ToolResultBlock):
                        print(f"DEBUG: ToolResult for tool_use_id {block.tool_use_id}")
                        result = str(block.content)[:500]
                        yield f"data: {json.dumps({'type': 'tool_result', 'result': result})}\n\n"

                        # Retrieve corresponding tool use
                        tool_use = pending_tool_uses.get(block.tool_use_id)
                        
                        if tool_use:
                            file_path = get_file_path_from_tool(
                                tool_use['name'],
                                tool_use['input']
                            )
                            print(f"DEBUG: Extracted file path: {file_path}")
                            if file_path:
                                print(f"DEBUG: Emitting file_change for {file_path}")

                                action = "created"
                                if tool_use['name'] in ("Edit", "replace_file_content", "multi_replace_file_content"):
                                    action = "modified"

                                logical_path = _ensure_session_copy(sandbox, sid, file_path)
                                if logical_path and logical_path not in doc_generation_announced and is_document_file(logical_path):
                                    doc_generation_announced.add(logical_path)
                                    status_event = {
                                        'type': 'status',
                                        'content': 'doc_generation_requested',
                                        'path': logical_path,
                                    }
                                    yield f"data: {json.dumps(status_event)}\n\n"

                                # Validate file exists with content before emitting file_change
                                if logical_path:
                                    full_path = session_storage_path(sid, logical_path)
                                    # For binary docs (docx, pptx, xlsx, pdf), require min 100 bytes
                                    # For text files, just require non-empty
                                    ext = Path(logical_path).suffix.lower()
                                    min_size = 100 if ext in {'.docx', '.pptx', '.xlsx', '.pdf'} else 1

                                    if validate_file_in_sandbox(sandbox, full_path, min_size):
                                        file_event = {
                                            'type': 'file_change',
                                            'path': logical_path,
                                            'action': action,
                                            'timestamp': time.time()
                                        }
                                        yield f"data: {json.dumps(file_event)}\n\n"
                                        known_files.add(logical_path)
                                        files_emitted = True
                                    else:
                                        print(f"DEBUG: File validation failed for {full_path}, skipping file_change event")

                            # Also scan for any new document files after Bash commands
                            if tool_use['name'] in ("Bash", "run_command"):
                                new_docs = scan_for_new_documents(sandbox, known_files, sid)
                                print(f"DEBUG: Scanned new docs: {new_docs}")
                                for doc_path in new_docs:
                                    doc_path = _ensure_session_copy(sandbox, sid, doc_path) or doc_path
                                    if doc_path not in doc_generation_announced and is_document_file(doc_path):
                                        doc_generation_announced.add(doc_path)
                                        status_event = {
                                            'type': 'status',
                                            'content': 'doc_generation_requested',
                                            'path': doc_path,
                                        }
                                        yield f"data: {json.dumps(status_event)}\n\n"

                                    # Validate file before emitting file_change
                                    full_path = session_storage_path(sid, doc_path)
                                    ext = Path(doc_path).suffix.lower()
                                    min_size = 100 if ext in {'.docx', '.pptx', '.xlsx', '.pdf'} else 1

                                    if validate_file_in_sandbox(sandbox, full_path, min_size):
                                        file_event = {
                                            'type': 'file_change',
                                            'path': doc_path,
                                            'action': 'created',
                                            'timestamp': time.time()
                                        }
                                        yield f"data: {json.dumps(file_event)}\n\n"
                                        known_files.add(doc_path)
                                        files_emitted = True
                                    else:
                                        print(f"DEBUG: File validation failed for {full_path}, skipping file_change")

                                fallback_docs = scan_for_new_documents_global(sandbox, known_files, sid)
                                print(f"DEBUG: Scanned global docs: {fallback_docs}")
                                for doc_path in fallback_docs:
                                    if doc_path not in doc_generation_announced and is_document_file(doc_path):
                                        doc_generation_announced.add(doc_path)
                                        status_event = {
                                            'type': 'status',
                                            'content': 'doc_generation_requested',
                                            'path': doc_path,
                                        }
                                        yield f"data: {json.dumps(status_event)}\n\n"

                                    # Validate file before emitting file_change
                                    full_path = session_storage_path(sid, doc_path)
                                    ext = Path(doc_path).suffix.lower()
                                    min_size = 100 if ext in {'.docx', '.pptx', '.xlsx', '.pdf'} else 1

                                    if validate_file_in_sandbox(sandbox, full_path, min_size):
                                        file_event = {
                                            'type': 'file_change',
                                            'path': doc_path,
                                            'action': 'created',
                                            'timestamp': time.time()
                                        }
                                        yield f"data: {json.dumps(file_event)}\n\n"
                                        known_files.add(doc_path)
                                        files_emitted = True
                                    else:
                                        print(f"DEBUG: File validation failed for {full_path}, skipping file_change")
                            
                            # Clean up processed tool use
                            del pending_tool_uses[block.tool_use_id]
                        else:
                            print(f"DEBUG: No pending tool use found for id {block.tool_use_id}")

                        last_tool_use = None
                    elif isinstance(block, TextBlock):
                        event = {'type': 'text_delta', 'content': block.text}
                        yield f"data: {json.dumps(event)}\n\n"

            elif isinstance(msg, SystemMessage):
                # Surface system messages to the client and continue the stream instead of crashing
                sys_text = []
                try:
                    for block in getattr(msg, "content", []) or []:
                        if isinstance(block, TextBlock):
                            sys_text.append(block.text)
                        else:
                            sys_text.append(str(block))
                except Exception as exc:
                    sys_text.append(f"(unreadable system content: {exc})")

                payload = {
                    "type": "status",
                    "content": "system_message",
                    "detail": "\n".join(sys_text).strip(),
                }
                print(f"[stream] forwarding SystemMessage: {payload}")
                yield f"data: {json.dumps(payload)}\n\n"

            elif isinstance(msg, ResultMessage):
                print(f"[stream] received ResultMessage for session {sid}")
                if doc_intent and not files_emitted:
                    fail_event = {
                        "type": "status",
                        "content": "doc_generation_failed",
                        "path": next(iter(doc_generation_announced), None),
                    }
                    yield f"data: {json.dumps(fail_event)}\n\n"
                event = {'type': 'complete', 'content': msg.result or ''}
                yield f"data: {json.dumps(event)}\n\n"
                usage = msg.usage or {}
                cost = msg.total_cost_usd or 0.0
                existing = SESSION_USAGE.get(sid, {"total_cost_usd": 0.0, "usage": {}})
                existing["total_cost_usd"] = round(existing["total_cost_usd"] + cost, 6)
                for key, value in usage.items():
                    if isinstance(value, (int, float)):
                        existing["usage"][key] = existing["usage"].get(key, 0) + value
                    else:
                        existing["usage"][key] = value
                SESSION_USAGE[sid] = existing
                usage_event = {
                    "type": "usage",
                    "session_id": sid,
                    "total_cost_usd": existing["total_cost_usd"],
                    "usage": existing["usage"],
                }
                print(f"[stream] session {sid} usage updated: {usage_event}")
                yield f"data: {json.dumps(usage_event)}\n\n"

    except Exception as e:
        error_payload = {
            "type": "error",
            "content": str(e),
            "traceback": traceback.format_exc(),
        }
        if isinstance(e, BaseExceptionGroup):
            error_payload["sub_errors"] = [
                f"{type(sub).__name__}: {sub}" for sub in e.exceptions
            ]
        if stderr_lines:
            error_payload["stderr"] = "\n".join(stderr_lines[-200:])
        yield f"data: {json.dumps(error_payload)}\n\n"


@router.post("/stream")
async def stream_message(
    chat_message: ChatMessage,
    user=Depends(get_current_user),
):
    """Stream chat responses using SSE."""
    print("[stream] stream_message start user_id=%s session_id=%s", user["uid"], chat_message.session_id)
    return StreamingResponse(
        agent_event_generator(chat_message.message, user["uid"], chat_message.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user=Depends(get_current_user),
):
    """Delete a session and its associated sandbox."""
    session_user = SESSION_USERS.get(session_id)
    if session_user and session_user != user["uid"]:
        return {"status": "forbidden", "message": "Session not found"}

    sandbox = sandbox_manager.get_sandbox(user["uid"])
    if sandbox:
        sandbox_manager.close_sandbox(user["uid"])
    SESSION_USAGE.pop(session_id, None)
    SESSION_USERS.pop(session_id, None)
    return {"status": "success", "message": f"Session {session_id} deleted"}

    return {"status": "not_found", "message": "Session not found"}


@router.get("/{session_id}/usage")
async def get_session_usage(
    session_id: str,
    user=Depends(get_current_user),
):
    """Get token usage and cost totals for a session."""
    session_user = SESSION_USERS.get(session_id)
    if session_user and session_user != user["uid"]:
        return {"total_cost_usd": 0.0, "usage": {}}
    return SESSION_USAGE.get(session_id, {"total_cost_usd": 0.0, "usage": {}})
