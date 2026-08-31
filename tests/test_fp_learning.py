import json

from lattice_ai.review import generate_findings
from lattice_ai.selfcheck import evolution_report


class CapturingProvider:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return self.reply


def test_generate_findings_injects_fp_keys():
    p = CapturingProvider({"content": "[]"})
    generate_findings(p, {}, {}, "", known_false_positives=["k1"])
    assert "k1" in json.dumps(p.calls[0], ensure_ascii=False)


def test_evolution_report_injects_fp_stats():
    p = CapturingProvider({
        "content": '{"summary":"s","steps":[],"suggestions":[],"unresolved":[],"confidence":"low"}',
    })
    evolution_report(p, {}, [], [], fp_stats={"known_false_positives": 3})
    prompt = p.calls[0][0]["content"]
    assert '"known_false_positives": 3' in prompt
