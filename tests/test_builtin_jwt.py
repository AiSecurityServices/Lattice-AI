import base64
import json

from lattice_ai.builtins import _jwt_analyze


def _b64(segment: str) -> str:
    return base64.urlsafe_b64encode(segment.encode("utf-8")).decode("utf-8").rstrip("=")


def _jwt(header: dict, payload: dict) -> str:
    return f"{_b64(json.dumps(header))}.{_b64(json.dumps(payload))}.sig"


def test_jwt_analyze_detects_alg_none():
    token = _jwt({"alg": "none", "typ": "JWT"}, {"sub": "admin"})
    result = _jwt_analyze({"jwt": token})
    types = {v["type"] for v in result["vulnerabilities"]}
    assert "alg_none" in types
    assert result["header"]["alg"] == "none"


def test_jwt_analyze_marks_rs_to_hs_downgrade():
    token = _jwt({"alg": "HS256", "typ": "JWT", "jwk": {"kty": "RSA"}}, {"sub": "admin"})
    result = _jwt_analyze({"jwt": token})
    types = {v["type"] for v in result["vulnerabilities"]}
    assert "rs_to_hs" in types


def test_jwt_analyze_flags_kid_injection():
    token = _jwt({"alg": "HS256", "kid": "../../etc/passwd"}, {"sub": "admin"})
    result = _jwt_analyze({"jwt": token})
    types = {v["type"] for v in result["vulnerabilities"]}
    assert "kid_injection" in types


def test_jwt_analyze_clean_token_has_no_vulnerabilities():
    token = _jwt({"alg": "RS256", "typ": "JWT"}, {"sub": "user"})
    result = _jwt_analyze({"jwt": token})
    assert result["vulnerabilities"] == []
    assert result["payload"]["sub"] == "user"
