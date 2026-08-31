from lattice_ai.danger import add_whitelist, danger_policy_default, evaluate_danger
from lattice_ai.models import Tool


def test_recon_tool_is_allowed():
    policy = danger_policy_default()
    tool = Tool(name="nmap", command=["nmap", "-sT", "{target}"], runner="cli")
    verdict = evaluate_danger(policy, tool, {"target": "example.com"})
    assert verdict.action == "allow"


def test_sqlmap_dump_is_data_exfil():
    tool = Tool(name="sqlmap", command=["sqlmap", "-u", "{target}", "--dump"], runner="cli")
    verdict = evaluate_danger(danger_policy_default(), tool, {"target": "https://example.com"})
    assert verdict.category == "data-exfil"
    # lenient default lets data-exfil run; standard asks first
    assert verdict.action == "allow"
    standard = {"level": "standard", "whitelist": []}
    assert evaluate_danger(standard, tool, {"target": "https://example.com"}).action == "ask"


def test_strict_denies_destructive():
    policy = danger_policy_default()
    policy["level"] = "strict"
    tool = Tool(name="shell", command=["rm", "-rf", "{target}"], runner="cli")
    verdict = evaluate_danger(policy, tool, {"target": "/tmp/x"})
    assert verdict.action == "deny"


def test_whitelist_allows_matching_tool_category():
    policy = danger_policy_default()
    policy = add_whitelist(policy, "sqlmap", "data-exfil")
    tool = Tool(name="sqlmap", command=["sqlmap", "--dump"], runner="cli")
    verdict = evaluate_danger(policy, tool, {"target": "https://example.com"})
    assert verdict.action == "allow"
