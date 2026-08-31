import pytest


@pytest.fixture(autouse=True)
def _disable_remote_auth(monkeypatch):
    """API tests talk through the ASGI transport whose peer host is not a
    loopback address, so remote-token auth is disabled globally; the auth
    behavior itself is covered in test_security.py."""
    monkeypatch.setenv("LATTICE_AUTH_DISABLED", "1")
