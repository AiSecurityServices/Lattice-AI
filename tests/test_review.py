from lattice_ai.review import generate_report, generate_report_stream, review_workflow, understand_workflow


class FakeProvider:
    def __init__(self, content):
        self.content = content

    def chat(self, messages, tools):
        return {"content": self.content, "tool_calls": []}


def test_review_workflow_parses_issues():
    provider = FakeProvider('[{"severity": "error", "where": "a", "message": "no tools"}]')
    issues = review_workflow(provider, {"id": "t"})
    assert issues == [{"severity": "error", "where": "a", "message": "no tools"}]


def test_review_workflow_no_json():
    provider = FakeProvider("no json here")
    assert review_workflow(provider, {}) == []


def test_understand_workflow_keeps_dag_stages():
    class Fake:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"content": "summary", "tool_calls": []}
            return {"content": "[]", "tool_calls": []}

    template = {
        "id": "t",
        "name": "n",
        "start": "a",
        "stages": [{"id": "a", "name": "a", "depends_on": [], "tools": [{"tool": "scan", "key": "scan"}]}],
        "tools": [],
    }
    updated, issues = understand_workflow(Fake(), template)
    assert updated["stages"][0]["depends_on"] == []
    assert "transitions" not in updated
    assert updated["summary"] == "summary"
    assert issues == []


def test_generate_report():
    provider = FakeProvider("## 目标\nexample.com\n\n## 发现\n- 80\n- 443")
    report = generate_report(provider, {"ports": {"stdout": "80,443"}}, {"name": "demo"})
    assert "example.com" in report


def test_generate_report_stream_emits_deltas():
    class StreamProvider:
        def stream_chat(self, messages, tools):
            yield {"type": "delta", "content": "## Report\n"}
            yield {"type": "delta", "content": "example.com"}
            yield {"type": "done", "content": "## Report\nexample.com", "tool_calls": []}

    chunks = []
    report = generate_report_stream(StreamProvider(), {"ports": {"stdout": "80"}}, {"name": "demo"}, on_delta=chunks.append)
    assert report == "## Report\nexample.com"
    assert "".join(chunks) == "## Report\nexample.com"
