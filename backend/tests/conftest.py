import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Isolate job files under a temporary uploads directory."""
    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("UPLOAD_DIR", str(upload_root))

    import config
    import utils.paths as paths_module

    monkeypatch.setattr(config, "UPLOAD_DIR", upload_root)
    monkeypatch.setattr(paths_module, "UPLOAD_DIR", upload_root)
    return upload_root
