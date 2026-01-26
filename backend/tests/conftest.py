import pytest

from sandbox_manager import SandboxManager


@pytest.fixture(autouse=True)
def cleanup_sandboxes():
    """Ensure any sandboxes created during a test are torn down."""
    yield
    SandboxManager.close_all_instances()
