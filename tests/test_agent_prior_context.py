from lattice_ai.agent import StageAgent, WorkflowAgent, _prior_context_text
from lattice_ai.events import EventLog
from lattice_ai.models import Stage, Template
from lattice_ai.tools import ToolRegistry


class _Capture:
    def __init__(self):
        self.messages = None

    def chat(self, messages, tools):
        self.messages = messages
        return {"content": "done", "tool_calls": []}


def test_prior_context_text_mentions_false_positives():
    text = _prior_context_text({"known_false_positives": ["k1"], "prior_findings": []})
    assert "k1" in text


def test_stage_agent_injects_prior_context(tmp_path):
    cap = _Capture()
    agent = StageAgent(
        cap, ToolRegistry(), EventLog(tmp_path / "s.jsonl"),
        prior_context={"known_false_positives": ["k1"]},
    )
    agent.run_stage(Stage(id="a", name="A"), "example.com", {})
    assert "k1" in cap.messages[0]["content"]


def test_workflow_agent_injects_prior_context(tmp_path):
    cap = _Capture()
    agent = WorkflowAgent(
        cap, ToolRegistry(), EventLog(tmp_path / "s.jsonl"),
        prior_context={"known_false_positives": ["k1"]},
    )
    agent.run(Template(id="t", name="T", start="a", stages=[Stage(id="a", name="A")]), "example.com")
    assert "k1" in cap.messages[0]["content"]
