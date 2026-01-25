import os
import logging
from pathlib import Path
from typing import Optional, Dict
from e2b_code_interpreter import Sandbox
from firebase_admin import firestore

from firebase_admin_client import get_firestore_client

# Configure logging
logger = logging.getLogger(__name__)

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
            logger.info(f"Reusing existing sandbox for user {user_id}")
            return self.sandboxes[user_id]

        sandbox = None
        doc_ref = self.firestore.collection("user_sandboxes").document(user_id)

        # Try to reconnect to existing sandbox
        try:
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict() or {}
                sandbox_id = data.get("sandbox_id")
                if sandbox_id:
                    logger.info(f"Attempting to reconnect to sandbox {sandbox_id} for user {user_id}")
                    try:
                        sandbox = Sandbox.connect(sandbox_id, timeout=self.sandbox_timeout)
                        logger.info(f"Successfully reconnected to sandbox {sandbox_id}")
                    except Exception as e:
                        logger.warning(f"Failed to reconnect to sandbox {sandbox_id}: {e}")
                        # Clean up stale Firestore record
                        try:
                            doc_ref.delete()
                            logger.info(f"Deleted stale sandbox record for user {user_id}")
                        except Exception as cleanup_error:
                            logger.error(f"Failed to delete stale record: {cleanup_error}")
                        sandbox = None
        except Exception as e:
            logger.error(f"Error querying Firestore for user {user_id}: {e}")

        # Create new sandbox if reconnection failed
        if sandbox is None:
            logger.info(f"Creating new sandbox for user {user_id}")
            try:
                sandbox = Sandbox.create(
                    timeout=self.sandbox_timeout,
                    template=self.template,
                )
                logger.info(f"Created sandbox {sandbox.sandbox_id} for user {user_id}")

                # Store sandbox ID in Firestore
                try:
                    doc_ref.set(
                        {
                            "sandbox_id": sandbox.sandbox_id,
                            "updated_at": firestore.SERVER_TIMESTAMP,
                        },
                        merge=True,
                    )
                    logger.info(f"Stored sandbox ID in Firestore for user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to store sandbox ID in Firestore: {e}")
                    # Continue anyway - sandbox is created, just not persisted

            except Exception as e:
                logger.error(f"Failed to create sandbox for user {user_id}: {e}")
                raise RuntimeError(f"Failed to create sandbox: {e}")
        
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
        logger.info("Initializing sandbox with template files")
        self._ensure_root_dir(sandbox)

        # Copy template data files
        if self.data_dir.exists():
            file_count = 0
            for file_path in self.data_dir.glob("*"):
                if file_path.is_file():
                    try:
                        content = file_path.read_bytes()
                        sandbox.files.write(f"{SANDBOX_ROOT}/{file_path.name}", content)
                        file_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to copy data file {file_path.name}: {e}")
            logger.info(f"Copied {file_count} template data files")

        # Copy scripts
        if self.scripts_dir.exists():
            try:
                sandbox.files.make_dir(f"{SANDBOX_ROOT}/scripts")
            except Exception:
                pass  # Directory may already exist

            script_count = 0
            for file_path in self.scripts_dir.glob("*.py"):
                if file_path.is_file():
                    try:
                        content = file_path.read_bytes()
                        sandbox.files.write(f"{SANDBOX_ROOT}/scripts/{file_path.name}", content)
                        script_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to copy script {file_path.name}: {e}")
            logger.info(f"Copied {script_count} script files")

        # Copy skills directory
        if self.skills_dir.exists():
            logger.info("Copying skills directory")
            self._copy_directory_to_sandbox(sandbox, self.skills_dir, f"{SANDBOX_ROOT}/skills")
            logger.info("Sandbox initialization complete")
    
    def _copy_directory_to_sandbox(self, sandbox: Sandbox, local_dir: Path, remote_path: str):
        """Recursively copy a directory to the sandbox."""
        try:
            sandbox.files.make_dir(remote_path)
        except Exception:
            pass  # Directory may already exist

        for item in local_dir.iterdir():
            remote_item_path = f"{remote_path}/{item.name}"

            if item.is_file():
                try:
                    content = item.read_bytes()
                    sandbox.files.write(remote_item_path, content)
                except Exception as e:
                    logger.warning(f"Failed to copy {item.name} to sandbox: {e}")
            elif item.is_dir():
                self._copy_directory_to_sandbox(sandbox, item, remote_item_path)
    
    def write_file(self, sandbox: Sandbox, path: str, content: str):
        """Write a file to the sandbox.

        Args:
            sandbox: The sandbox instance
            path: Path within sandbox (must not escape SANDBOX_ROOT)
            content: File content (string or bytes)

        Raises:
            ValueError: If path is invalid or escapes sandbox root
            RuntimeError: If sandbox is not running or write fails
        """
        if not sandbox:
            raise RuntimeError("Sandbox is not initialized")

        # Validate path doesn't escape sandbox root
        if ".." in path or path.startswith("/"):
            # Normalize and check
            from pathlib import PurePosixPath
            normalized = str(PurePosixPath(SANDBOX_ROOT) / path)
            if not normalized.startswith(SANDBOX_ROOT):
                raise ValueError(f"Path escapes sandbox root: {path}")

        try:
            if not sandbox.is_running():
                raise RuntimeError("Sandbox is not running")
            sandbox.files.write(path, content)
        except Exception as e:
            raise RuntimeError(f"Failed to write file {path}: {e}")

    def read_file(self, sandbox: Sandbox, path: str) -> str:
        """Read a file from the sandbox.

        Args:
            sandbox: The sandbox instance
            path: Path within sandbox

        Returns:
            File content as string

        Raises:
            RuntimeError: If sandbox is not running or read fails
        """
        if not sandbox:
            raise RuntimeError("Sandbox is not initialized")

        try:
            if not sandbox.is_running():
                raise RuntimeError("Sandbox is not running")
            return sandbox.files.read(path)
        except Exception as e:
            raise RuntimeError(f"Failed to read file {path}: {e}")

    def list_files(self, sandbox: Sandbox, path: str = SANDBOX_ROOT) -> list:
        """List files in the sandbox directory.

        Args:
            sandbox: The sandbox instance
            path: Directory path within sandbox

        Returns:
            List of file entries

        Raises:
            RuntimeError: If sandbox is not running or list fails
        """
        if not sandbox:
            raise RuntimeError("Sandbox is not initialized")

        try:
            if not sandbox.is_running():
                raise RuntimeError("Sandbox is not running")
            return sandbox.files.list(path)
        except Exception as e:
            raise RuntimeError(f"Failed to list directory {path}: {e}")

    def execute_command(self, sandbox: Sandbox, command: str, timeout: int = 120) -> str:
        """Execute a bash command in the sandbox.

        Args:
            sandbox: The sandbox instance
            command: Command to execute
            timeout: Timeout in seconds (default: 120)

        Returns:
            Combined stdout and stderr output

        Raises:
            RuntimeError: If sandbox is not running or execution fails
        """
        if not sandbox:
            raise RuntimeError("Sandbox is not initialized")

        try:
            if not sandbox.is_running():
                raise RuntimeError("Sandbox is not running")

            # E2B Code Interpreter only supports run_code() for Python
            # So we execute bash commands via Python subprocess
            python_code = f'''
import subprocess
import os

env = os.environ.copy()
env["TMPDIR"] = "{SANDBOX_TMP}"
env["NODE_PATH"] = "/usr/local/lib/node_modules"

try:
    result = subprocess.run(
        ["bash", "-c", {repr(command)}],
        capture_output=True,
        text=True,
        cwd="{SANDBOX_ROOT}",
        env=env,
        timeout={timeout}
    )

    output = []
    if result.stdout:
        output.append(result.stdout)
    if result.stderr:
        output.append(result.stderr)

    if result.returncode != 0 and not result.stderr:
        output.append(f"Command exited with code {{result.returncode}}")

    print("\\n".join(output) if output else "")

except subprocess.TimeoutExpired:
    print(f"Error: Command timed out after {timeout} seconds")
except Exception as e:
    print(f"Error: {{type(e).__name__}}: {{e}}")
'''

            execution = sandbox.run_code(python_code)

            # Combine stdout and stderr
            output_parts = []
            if execution.logs.stdout:
                output_parts.extend(execution.logs.stdout)
            if execution.logs.stderr:
                output_parts.extend(execution.logs.stderr)

            output = "\n".join(output_parts) if output_parts else ""

            # Check for execution errors
            if execution.error and not output.strip():
                output = f"Execution error: {execution.error}"

            return output
        except Exception as e:
            raise RuntimeError(f"Failed to execute command: {e}")
    
    def close_sandbox(self, user_id: str):
        """Close and cleanup a sandbox.

        Args:
            user_id: User ID whose sandbox should be closed
        """
        if user_id in self.sandboxes:
            sandbox = self.sandboxes[user_id]
            sandbox_id = getattr(sandbox, 'sandbox_id', 'unknown')

            try:
                logger.info(f"Closing sandbox {sandbox_id} for user {user_id}")
                sandbox.close()
                logger.info(f"Successfully closed sandbox {sandbox_id}")
            except Exception as e:
                logger.error(f"Error closing sandbox {sandbox_id}: {e}")

            # Remove from in-memory cache regardless of close result
            del self.sandboxes[user_id]

            # Clean up Firestore record
            try:
                doc_ref = self.firestore.collection("user_sandboxes").document(user_id)
                doc_ref.delete()
                logger.info(f"Deleted Firestore record for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete Firestore record for user {user_id}: {e}")
    
    def close_all(self):
        """Close all sandboxes."""
        for user_id in list(self.sandboxes.keys()):
            self.close_sandbox(user_id)
