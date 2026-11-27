import os
import shutil

import pytest

# Point the backend at the test database before anything imports it,
# so running pytest never wipes the real local data.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://courtiq:courtiq@localhost:5432/courtiq_test",
)


@pytest.fixture
def test_storage(monkeypatch):
    """Files the API saves during a test go to storage/test/, wiped after each test, so they
    never mix with (or delete) real files in storage/."""
    import backend.app as api

    root = api.PROJECT_ROOT / "storage" / "test"
    monkeypatch.setattr(api, "UPLOAD_ROOT", root / "uploads")
    monkeypatch.setattr(api, "RESULT_ROOT", root / "results")
    yield
    shutil.rmtree(root, ignore_errors=True)
