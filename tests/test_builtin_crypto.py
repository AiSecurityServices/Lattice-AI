from lattice_ai.builtins import _crypto_analyze


def test_crypto_analyze_extracts_aes_key():
    text = 'const AES_KEY = "1234567890123456";'
    result = _crypto_analyze({"text": text})
    assert any(k["type"] == "AES" and k["key"] == "1234567890123456" for k in result["keys"])


def test_crypto_analyze_extracts_rsa_and_des_keys():
    text = "private_key = 'MIICdgIBADANBgkqhkiG9w0BAQEF'; DES_KEY='abcdefgh'"
    result = _crypto_analyze({"text": text})
    types = {k["type"] for k in result["keys"]}
    assert "RSA" in types
    assert "DES" in types


def test_crypto_analyze_flags_short_des_key():
    text = "DES_KEY='abc'"
    result = _crypto_analyze({"text": text})
    assert any(w["type"] == "DES" and "short" in w["detail"] for w in result["weak"])
