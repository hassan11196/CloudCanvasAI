import json
import time
import uuid
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Optional, Any
import re
import traceback

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
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from sandbox_manager import SandboxManager, SANDBOX_ROOT
from auth import get_current_user

# Document-focused tools for the skills integration
DOCUMENT_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]

# File extensions that trigger document preview
DOCUMENT_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".pdf", ".md", ".txt", ".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".py"}

# Path to the docx creation script
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
SKILLS_DIR = Path(__file__).parent.parent / "skills"

# System prompt for document creation capabilities
DOCUMENT_SYSTEM_PROMPT = """
You are Zephior, an AI assistant with document creation capabilities.
"""
SKILL_NAMES = ("docx", "pdf", "pptx", "xlsx")
SKILL_PATH_NOTE = (
    "Skill assets are available under /skills/{docx,pdf,pptx,xlsx}. "
    "When instructions reference relative paths like ooxml/scripts or scripts/thumbnail.py, "
    "run them from the appropriate skill directory or use absolute paths under /skills. "
    "Use /home/user/workspace for working files and /home/user/tmp for temporary files. "
    "If Node.js or docx-js dependencies are unavailable, prefer /home/user/scripts/create_docx.py "
    "to generate .docx files."
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


def should_use_sandbox(message: str) -> bool:
    lowered = message.lower()
    if any(ext in lowered for ext in (".docx", ".pptx", ".xlsx", ".pdf")):
        return True
    for keyword in FILE_KEYWORDS:
        if keyword in lowered:
            return True
    return False

router = APIRouter(prefix="/chat", tags=["chat"])

# Initialize E2B sandbox manager
sandbox_manager = SandboxManager()
SESSION_USAGE: dict[str, dict[str, Any]] = {}
SESSION_USERS: dict[str, str] = {}


def get_or_create_session(
    user_id: str,
    session_id: Optional[str] = None,
) -> tuple[str, object]:
    """Get existing session or create new one with isolated E2B sandbox."""
    if session_id:
        sandbox = sandbox_manager.get_sandbox(user_id)
        if sandbox:
            return session_id, sandbox
        sandbox = sandbox_manager.create_sandbox(user_id)
        return session_id, sandbox

    # Create new session with E2B sandbox
    new_id = str(uuid.uuid4())
    sandbox = sandbox_manager.create_sandbox(user_id)
    return new_id, sandbox


class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None


def get_file_path_from_tool(tool_name: str, tool_input: dict) -> Optional[str]:
    """Extract file path from Write, Edit, or Bash tool input."""
    import re

    if tool_name in ("Write", "Edit", "write_to_file", "replace_file_content", "multi_replace_file_content"):
        return tool_input.get("file_path") or tool_input.get("TargetFile") or tool_input.get("path")
    elif tool_name in ("Bash", "run_command"):
        command = tool_input.get("command") or tool_input.get("CommandLine") or ""
        # Check if this is a create_docx.py command
        if "create_docx.py" in command:
            # Extract the output filename - look for .docx file in command
            docx_match = re.search(r'(\S+\.docx)', command)
            if docx_match:
                return docx_match.group(1)
        doc_match = re.search(r"(\S+\.(?:docx|pptx|xlsx|pdf))", command)
        if doc_match:
            return doc_match.group(1)
    return None


def scan_for_new_documents(sandbox, known_files: set) -> list[str]:
    """Scan E2B sandbox for any new document files."""
    new_files = []
    try:
        entries = _iter_sandbox_files(sandbox, SANDBOX_ROOT)
        for rel_path, is_dir in entries:
            if is_dir:
                continue
            if any(rel_path.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
                if rel_path not in known_files:
                    new_files.append(rel_path)
                    known_files.add(rel_path)
    except Exception as e:
        print(f"Error scanning for documents: {e}")
    return new_files


def is_document_file(file_path: str) -> bool:
    """Check if file is a document type we want to preview."""
    if not file_path:
        return False
    ext = Path(file_path).suffix.lower()
    return ext in DOCUMENT_EXTENSIONS


def _extract_tool_path(tool_input: dict) -> Optional[str]:
    return (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("TargetFile")
        or tool_input.get("target_file")
    )


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


def _build_sandbox_mcp_server(sandbox):
    read_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "path": {"type": "string"},
        },
    }
    write_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
    }
    edit_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "path": {"type": "string"},
            "content": {"type": "string"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                },
            },
        },
    }
    glob_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
    }
    grep_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
    }
    bash_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
        },
    }

    @tool("Read", "Read a file from the sandbox filesystem", read_schema)
    async def read_tool(args):
        try:
            target_path = _resolve_sandbox_path(_extract_tool_path(args))
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
            target_path = _resolve_sandbox_path(_extract_tool_path(args))
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
            target_path = _resolve_sandbox_path(_extract_tool_path(args))
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
            sandbox_tmp = f"{SANDBOX_ROOT}/tmp"
            python_code = (
                "import os, subprocess, json\n"
                f"cmd = {json.dumps(command)}\n"
                "env = os.environ.copy()\n"
                f"env['TMPDIR'] = {json.dumps(sandbox_tmp)}\n"
                f"cwd = {json.dumps(SANDBOX_ROOT)}\n"
                "shell = '/bin/bash' if os.path.exists('/bin/bash') else '/bin/sh'\n"
                "result = subprocess.run([shell, '-lc', cmd], capture_output=True, text=True, env=env, cwd=cwd)\n"
                "print(f'Exit code: {result.returncode}')\n"
                "print(result.stdout, end='')\n"
                "print(result.stderr, end='')\n"
            )
            execution = sandbox.run_code(python_code)
            output = ""
            if execution.logs.stdout:
                output += "\n".join(execution.logs.stdout)
            if execution.logs.stderr:
                output += "\n".join(execution.logs.stderr)
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
    use_sandbox = should_use_sandbox(message)
    if use_sandbox:
        yield f"data: {json.dumps({'type': 'status', 'content': 'Starting sandbox'})}\n\n"
        sid, sandbox = get_or_create_session(user_id, session_id)
        is_resume = session_id is not None
        SESSION_USERS[sid] = user_id
    else:
        sid = session_id or str(uuid.uuid4())
        sandbox = None
        is_resume = bool(session_id)
        SESSION_USERS[sid] = user_id

    yield f"data: {json.dumps({'type': 'session', 'session_id': sid})}\n\n"
    yield f"data: {json.dumps({'type': 'status', 'content': 'Preparing agent'})}\n\n"

    # Load system prompt from SKILL.md if available
    skill_prompt = DOCUMENT_SYSTEM_PROMPT.strip()
    skill_prompt += "\n\n" + SKILL_PATH_NOTE
    skills_dir = Path(__file__).parent.parent / "skills"
    for skill_name in SKILL_NAMES:
        skill_md_path = skills_dir / skill_name / "SKILL.md"
        if skill_md_path.exists():
            skill_prompt += f"\n\n# Skill: {skill_name}\n" + skill_md_path.read_text()

    # Build system prompt with E2B paths
    system_prompt = skill_prompt.replace(
        "/scripts/create_docx.py",
        f"{SANDBOX_ROOT}/scripts/create_docx.py"
    ).replace(
        "/skills",
        f"{SANDBOX_ROOT}/skills"
    )

    sandbox_server = _build_sandbox_mcp_server(sandbox) if sandbox else None
    stderr_lines: list[str] = []

    def _stderr_callback(line: str) -> None:
        stderr_lines.append(line)

    options = ClaudeAgentOptions(
        tools=[],
        allowed_tools=DOCUMENT_TOOLS if sandbox_server else [],
        permission_mode="bypassPermissions",
        cwd=None,
        resume=sid if is_resume else None,
        continue_conversation=is_resume,
        system_prompt=system_prompt,
        mcp_servers={"sandbox": sandbox_server} if sandbox_server else {},
        stderr=_stderr_callback,
        extra_args={"debug-to-stderr": None},
    )

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
    
    # Get initial file list from E2B sandbox
    if sandbox:
        try:
            entries = _iter_sandbox_files(sandbox, SANDBOX_ROOT)
            for rel_path, is_dir in entries:
                if is_dir:
                    continue
                if any(rel_path.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
                    known_files.add(rel_path)
        except Exception as e:
            print(f"Error listing initial files: {e}")

    try:
        async for msg in query(prompt=_prompt_stream(), options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ThinkingBlock):
                        event = {'type': 'thinking', 'content': block.thinking}
                        yield f"data: {json.dumps(event)}\n\n"
                    elif isinstance(block, ToolUseBlock):
                        # Store tool use by ID
                        pending_tool_uses[block.id] = {
                            'name': block.name,
                            'input': block.input
                        }
                        event = {
                            'type': 'tool_use',
                            'tool_name': block.name,
                            'tool_input': block.input
                        }
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

                                file_event = {
                                    'type': 'file_change',
                                    'path': file_path,
                                    'action': action,
                                    'timestamp': time.time()
                                }
                                yield f"data: {json.dumps(file_event)}\n\n"
                                known_files.add(file_path)

                            # Also scan for any new document files after Bash commands
                            if tool_use['name'] in ("Bash", "run_command"):
                                new_docs = scan_for_new_documents(sandbox, known_files)
                                print(f"DEBUG: Scanned new docs: {new_docs}")
                                for doc_path in new_docs:
                                    file_event = {
                                        'type': 'file_change',
                                        'path': doc_path,
                                        'action': 'created',
                                        'timestamp': time.time()
                                    }
                                    yield f"data: {json.dumps(file_event)}\n\n"
                            
                            # Clean up processed tool use
                            del pending_tool_uses[block.tool_use_id]
                        else:
                            print(f"DEBUG: No pending tool use found for id {block.tool_use_id}")

                        last_tool_use = None
                    elif isinstance(block, TextBlock):
                        event = {'type': 'text_delta', 'content': block.text}
                        yield f"data: {json.dumps(event)}\n\n"

            elif isinstance(msg, ResultMessage):
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
