import os
from pathlib import Path
from typing import Optional, Dict
import shutil
from e2b_code_interpreter import Sandbox
from firebase_admin import firestore

from firebase_admin_client import get_firestore_client

SANDBOX_ROOT = "/home/user"
SANDBOX_TMP = f"{SANDBOX_ROOT}/tmp"
SANDBOX_WORKSPACE = f"{SANDBOX_ROOT}/workspace"
DEFAULT_SANDBOX_TIMEOUT = int(os.getenv("E2B_SANDBOX_TIMEOUT", "3600"))


class SandboxManager:
    """Manages E2B sandbox lifecycle and operations."""
    
    def __init__(self):
        self.api_key = os.getenv("E2B_API_KEY")
        # Don't fail on init - check when creating sandbox

        self.sandbox_timeout = DEFAULT_SANDBOX_TIMEOUT
        self.template = os.getenv("E2B_TEMPLATE")
        
        # In-memory mapping of user_id -> Sandbox instance
        self.sandboxes: Dict[str, Sandbox] = {}
        self.firestore = get_firestore_client()
        
        # Template data directory
        self.data_dir = Path(__file__).parent / "very_imp_data"
        self.scripts_dir = Path(__file__).parent / "scripts"
        self.skills_dir = Path(__file__).parent / "skills"
    
    def create_sandbox(self, user_id: str) -> Sandbox:
        """Create a new E2B sandbox for the given user."""
        if not self.api_key:
            raise ValueError(
                "E2B_API_KEY environment variable is required. "
                "Please add your E2B API key to the .env file. "
                "Get your key from https://e2b.dev"
            )
        
        if user_id in self.sandboxes:
            return self.sandboxes[user_id]

        sandbox = None
        doc_ref = self.firestore.collection("user_sandboxes").document(user_id)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            sandbox_id = data.get("sandbox_id")
            if sandbox_id:
                try:
                    sandbox = Sandbox.connect(sandbox_id, timeout=self.sandbox_timeout)
                except Exception:
                    sandbox = None

        if sandbox is None:
            sandbox = Sandbox.create(
                timeout=self.sandbox_timeout,
                template=self.template,
            )
            doc_ref.set(
                {
                    "sandbox_id": sandbox.sandbox_id,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
        
        # Initialize sandbox with template files
        self._initialize_sandbox(sandbox)
        
        # Store sandbox reference
        self.sandboxes[user_id] = sandbox
        
        return sandbox
    
    def get_sandbox(self, user_id: str) -> Optional[Sandbox]:
        """Get existing sandbox for the user."""
        sandbox = self.sandboxes.get(user_id)
        if not sandbox:
            return None

        try:
            if not sandbox.is_running():
                self.close_sandbox(user_id)
                return None
        except Exception:
            self.close_sandbox(user_id)
            return None

        return sandbox
    
    def _ensure_root_dir(self, sandbox: Sandbox):
        """Ensure the sandbox root directory exists."""
        for path in ("/home", SANDBOX_ROOT, SANDBOX_TMP, SANDBOX_WORKSPACE):
            try:
                sandbox.files.make_dir(path)
            except Exception:
                # Directory may already exist or be unavailable; ignore and proceed.
                pass

    def _initialize_sandbox(self, sandbox: Sandbox):
        """Initialize sandbox with template files, scripts, and skills."""
        self._ensure_root_dir(sandbox)

        # Copy template data files
        if self.data_dir.exists():
            for file_path in self.data_dir.glob("*"):
                if file_path.is_file():
                    content = file_path.read_text()
                    sandbox.files.write(f"{SANDBOX_ROOT}/{file_path.name}", content)
        
        # Copy scripts
        if self.scripts_dir.exists():
            sandbox.files.make_dir(f"{SANDBOX_ROOT}/scripts")
            for file_path in self.scripts_dir.glob("*.py"):
                if file_path.is_file():
                    content = file_path.read_text()
                    sandbox.files.write(f"{SANDBOX_ROOT}/scripts/{file_path.name}", content)
        
        # Copy skills directory
        if self.skills_dir.exists():
            self._copy_directory_to_sandbox(sandbox, self.skills_dir, f"{SANDBOX_ROOT}/skills")
    
    def _copy_directory_to_sandbox(self, sandbox: Sandbox, local_dir: Path, remote_path: str):
        """Recursively copy a directory to the sandbox."""
        for item in local_dir.iterdir():
            remote_item_path = f"{remote_path}/{item.name}"
            
            if item.is_file():
                content = item.read_text()
                sandbox.files.write(remote_item_path, content)
            elif item.is_dir():
                sandbox.files.make_dir(remote_item_path)
                self._copy_directory_to_sandbox(sandbox, item, remote_item_path)
    
    def write_file(self, sandbox: Sandbox, path: str, content: str):
        """Write a file to the sandbox."""
        sandbox.files.write(path, content)
    
    def read_file(self, sandbox: Sandbox, path: str) -> str:
        """Read a file from the sandbox."""
        return sandbox.files.read(path)
    
    def list_files(self, sandbox: Sandbox, path: str = SANDBOX_ROOT) -> list:
        """List files in the sandbox directory."""
        return sandbox.files.list(path)
    
    def execute_command(self, sandbox: Sandbox, command: str) -> str:
        """Execute a bash command in the sandbox."""
        execution = sandbox.run_code(command)
        
        # Combine stdout and stderr
        output = ""
        if execution.logs.stdout:
            output += "\n".join(execution.logs.stdout)
        if execution.logs.stderr:
            output += "\n".join(execution.logs.stderr)
        
        return output
    
    def close_sandbox(self, user_id: str):
        """Close and cleanup a sandbox."""
        if user_id in self.sandboxes:
            sandbox = self.sandboxes[user_id]
            sandbox.close()
            del self.sandboxes[user_id]
    
    def close_all(self):
        """Close all sandboxes."""
        for user_id in list(self.sandboxes.keys()):
            self.close_sandbox(user_id)
