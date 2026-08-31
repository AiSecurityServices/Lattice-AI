from lattice_ai.builtins import _fingerprint_cve


def test_fingerprint_cve_matches_log4j():
    result = _fingerprint_cve({"fingerprints": ["log4j 2.14.1"]})
    assert any("CVE-2021-44228" in m["cves"] for m in result["matches"])


def test_fingerprint_cve_matches_shiro_and_fastjson():
    result = _fingerprint_cve({"fingerprints": ["shiro 1.2.5", "fastjson 1.2.24"]})
    names = {m["name"] for m in result["matches"]}
    assert "Shiro 反序列化" in names
    assert "Fastjson RCE" in names


def test_fingerprint_cve_unknown_version_returns_no_matches():
    result = _fingerprint_cve({"fingerprints": ["spring 3.0.1"]})
    assert result["matches"] == []
