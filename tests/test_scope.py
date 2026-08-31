from lattice_ai.scope import ScopePolicy, evaluate_scope, is_restricted_target
from lattice_ai.tools import ToolRegistry
from lattice_ai.builtins import install_builtins


def test_subdomain_of_authorized_root_is_allowed():
    policy = ScopePolicy(allow_domains=["example.com"])
    ok, _ = evaluate_scope(policy, "api.example.com")
    assert ok


def test_nested_subdomain_of_authorized_root_is_allowed():
    policy = ScopePolicy(allow_domains=["example.com"])
    ok, _ = evaluate_scope(policy, "a.b.example.com")
    assert ok


def test_bare_domain_not_rejected_by_allow_ports():
    policy = ScopePolicy(allow_domains=["example.com"], allow_ports=[80, 443])
    ok, _ = evaluate_scope(policy, "example.com")
    assert ok


def test_allow_url_prefixes_does_not_block_domain_target():
    policy = ScopePolicy(allow_domains=["example.com"], allow_url_prefixes=["https://example.com/api/"])
    ok, _ = evaluate_scope(policy, "example.com")
    assert ok


def test_host_with_explicit_allowed_port_passes():
    policy = ScopePolicy(allow_domains=["example.com"], allow_ports=[443])
    ok, _ = evaluate_scope(policy, "https://example.com:443")
    assert ok


def test_out_of_scope_domain_blocked():
    policy = ScopePolicy(allow_domains=["example.com"])
    ok, _ = evaluate_scope(policy, "evil.com")
    assert not ok


def test_ip_and_cidr_enforced():
    policy = ScopePolicy(allow_cidrs=["10.0.0.0/8"])
    ok, _ = evaluate_scope(policy, "10.1.2.3")
    assert ok
    ok, _ = evaluate_scope(policy, "192.168.1.1")
    assert not ok


def test_unconfigured_scope_allows():
    ok, reason = evaluate_scope(ScopePolicy(), "example.com")
    assert ok
    assert reason == "scope not configured"


def test_restricted_public_infra_detected():
    assert is_restricted_target("something.gov")
    assert is_restricted_target("x.mil")
    assert is_restricted_target("203.0.113.7")  # documentation range
    assert not is_restricted_target("example.com")


def test_allow_ports_injected_into_port_scanner():
    reg = ToolRegistry()
    install_builtins(reg)
    captured = {}

    def fake_nmap(args):
        captured["args"] = args
        return {"open_ports": [], "target": args.get("target")}

    reg._builtins["nmap"] = fake_nmap
    reg.set_security_context(scope_policy={"allow_domains": ["example.com"], "allow_ports": [80, 443]})
    reg.run("nmap", {"target": "example.com"})
    assert captured["args"]["ports"] == [80, 443]


def test_explicit_ports_not_overridden_by_scope():
    reg = ToolRegistry()
    install_builtins(reg)
    captured = {}

    def fake_nmap(args):
        captured["args"] = args
        return {"open_ports": [], "target": args.get("target")}

    reg._builtins["nmap"] = fake_nmap
    reg.set_security_context(scope_policy={"allow_domains": ["example.com"], "allow_ports": [80, 443]})
    reg.run("nmap", {"target": "example.com", "ports": [8080]})
    assert captured["args"]["ports"] == [8080]
