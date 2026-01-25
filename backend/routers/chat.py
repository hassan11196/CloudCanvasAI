import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter

load_dotenv()
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

router = APIRouter(prefix="/chat", tags=["chat"])

# Session storage: session_id -> sandbox path
sessions: dict[str, Path] = {}

# Source data (read-only template)
DATA_DIR = Path(__file__).parent.parent / "very_imp_data"
# Sandboxed session directories
SANDBOX_DIR = Path(__file__).parent.parent / ".sandboxes"
SANDBOX_DIR.mkdir(exist_ok=True)


def get_or_create_session(session_id: Optional[str] = None) -> tuple[str, Path]:
    """Get existing session or create new one with isolated sandbox."""
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]
    
    # Create new session with its own sandbox
    new_id = str(uuid.uuid4())
    sandbox_path = SANDBOX_DIR / new_id
    sandbox_path.mkdir(exist_ok=True)
    
    # Copy template data to sandbox
    for src_file in DATA_DIR.glob("*"):
        if src_file.is_file():
            shutil.copy2(src_file, sandbox_path / src_file.name)
    
    sessions[new_id] = sandbox_path
    return new_id, sandbox_path


class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None


async def agent_event_generator(message: str, session_id: Optional[str] = None):
    """Generate SSE events from Claude agent execution."""
    sid, sandbox_path = get_or_create_session(session_id)
    is_resume = session_id and session_id in sessions
    
    yield f"data: {json.dumps({'type': 'session', 'session_id': sid})}\n\n"
    
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Write", "Glob", "Grep", "Bash"],
        permission_mode="acceptEdits",
        cwd=str(sandbox_path),
        resume=sid if is_resume else None,
        continue_conversation=is_resume,
    )
    
    try:
        async for msg in query(prompt=message, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ThinkingBlock):
                        yield f"data: {json.dumps({'type': 'thinking', 'content': block.thinking})}\n\n"
                    elif isinstance(block, ToolUseBlock):
                        yield f"data: {json.dumps({'type': 'tool_use', 'tool_name': block.name, 'tool_input': block.input})}\n\n"
                    elif isinstance(block, ToolResultBlock):
                        result = str(block.content)[:500]
                        yield f"data: {json.dumps({'type': 'tool_result', 'result': result})}\n\n"
                    elif isinstance(block, TextBlock):
                        yield f"data: {json.dumps({'type': 'text_delta', 'content': block.text})}\n\n"
            
            elif isinstance(msg, ResultMessage):
                yield f"data: {json.dumps({'type': 'complete', 'content': msg.result or ''})}\n\n"
                
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"


@router.post("/stream")
async def stream_message(chat_message: ChatMessage):
    """Stream chat responses using SSE."""
    return StreamingResponse(
        agent_event_generator(chat_message.message, chat_message.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )