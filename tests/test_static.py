from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lattice_ai import server
from lattice_ai import tools as tools_module

client = TestClient(server.app)

_WEB_DIST = Path(server.__file__).resolve().parent.parent.parent / "web" / "dist"
_HAS_DIST = _WEB_DIST.is_dir()


@pytest.fixture(autouse=True)
def _sandbox_extra_tool_paths(monkeypatch):
    """Serving the real app initializes the real project store, which registers
    the go bin dir in the module-level _EXTRA_TOOL_PATHS. Sandboxing that list
    keeps this module from leaking real executables (GOPATH/bin has nuclei & co.)
    into later tests that assert the missing-executable fallback."""
    monkeypatch.setattr(tools_module, "_EXTRA_TOOL_PATHS", [])


@pytest.mark.skipif(not _HAS_DIST, reason="web/dist not built")
def test_built_ui_served_from_same_origin():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="root"' in response.text


@pytest.mark.skipif(not _HAS_DIST, reason="web/dist not built")
def test_api_routes_take_precedence_over_static_mount():
    assert client.get("/health").status_code == 200
    assert client.get("/api/templates").status_code == 200


@pytest.mark.skipif(not _HAS_DIST, reason="web/dist not built")
def test_static_assets_served():
    index = client.get("/")
    asset_paths = [
        line.split('src="')[1].split('"')[0]
        for line in index.text.splitlines()
        if 'src="/assets/' in line
    ]
    assert asset_paths, "index.html should reference bundled assets"
    for asset in asset_paths:
        assert client.get(asset).status_code == 200
