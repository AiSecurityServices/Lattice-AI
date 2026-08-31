"""Resolve the runtime data directory.

Source checkouts keep their data next to the repository (``<repo>/data``).
Installed packages (``pip install lattice-ai``) fall back to a per-user
directory, because the site-packages tree must stay read-only and the repo
``data/`` folder does not travel with the wheel.

Override with the ``LATTICE_DATA_DIR`` environment variable.
"""
import os
from pathlib import Path


def data_root() -> Path:
    env = os.environ.get("LATTICE_DATA_DIR")
    if env:
        return Path(env).expanduser()
    repo_data = Path(__file__).resolve().parent.parent.parent / "data"
    try:
        if repo_data.is_dir() and os.access(repo_data, os.W_OK):
            return repo_data
    except OSError:
        pass
    return Path.home() / ".lattice-ai"
