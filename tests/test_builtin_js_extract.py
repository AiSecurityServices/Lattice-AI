from lattice_ai.builtins import _js_extract


def test_js_extract_axios_post_with_params():
    js = "axios.post('/api/user', {userId: 1, orgId: 'x'})"
    result = _js_extract({"js": js})
    endpoint = next(e for e in result["endpoints"] if e["url"] == "/api/user")
    assert endpoint["method"] == "POST"
    assert "userId" in endpoint["params"]
    assert "orgId" in endpoint["params"]


def test_js_extract_fetch_and_request_forms():
    js = """
    fetch('/api/login', {method: 'POST', body: JSON.stringify({username, password})})
    request({url: '/api/orders', method: 'get', data: {orderId, userId}})
    axios.get('/api/users?page=1&size=50')
    """
    result = _js_extract({"js": js})
    by_url = {e["url"]: e for e in result["endpoints"]}
    assert by_url["/api/login"]["method"] == "POST"
    assert {"username", "password"} <= set(by_url["/api/login"]["params"])
    assert by_url["/api/orders"]["method"] == "GET"
    assert {"orderId", "userId"} <= set(by_url["/api/orders"]["params"])
    assert {"page", "size"} <= set(by_url["/api/users"]["params"])


def test_js_extract_finds_secrets():
    js = "const API_KEY = 'sk_live_1234567890abcdef'; fetch('/api/x', {headers: {Authorization: 'Bearer ' + API_KEY}})"
    result = _js_extract({"js": js})
    assert any("sk_live_1234567890abcdef" in s for s in result["secrets"])


def test_js_extract_fetches_js_url(monkeypatch):
    from lattice_ai import builtins

    def fake_fetch(url, timeout=8):
        return url, 200, {}, "axios.get('/api/fetched', {token: 1})"

    monkeypatch.setattr(builtins, "_fetch", fake_fetch)
    result = _js_extract({"js": "http://example.com/app.js"})
    assert any(e["url"] == "/api/fetched" and e["method"] == "GET" for e in result["endpoints"])


def test_js_extract_fetches_list_of_js_urls(monkeypatch):
    from lattice_ai import builtins

    calls = []

    def fake_fetch(url, timeout=8):
        calls.append(url)
        return url, 200, {}, f"fetch('/api/{len(calls)}')"

    monkeypatch.setattr(builtins, "_fetch", fake_fetch)
    result = _js_extract({"js": ["http://example.com/a.js", "http://example.com/b.js"]})
    assert len(calls) == 2
    assert any(e["url"] == "/api/1" for e in result["endpoints"])
    assert any(e["url"] == "/api/2" for e in result["endpoints"])
