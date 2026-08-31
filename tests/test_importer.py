import pytest

from lattice_ai.importer import generate_tool_draft


class FakeProvider:
    def __init__(self, content):
        self.content = content

    def chat(self, messages, tools):
        return {"content": self.content, "tool_calls": []}


def test_generate_tool_draft():
    content = (
        'Here: {"name": "nmap", "description": "scan ports", "runner": "cli", '
        '"command": ["nmap", "{target}"], "parameters": {"type": "object", '
        '"properties": {"target": {"type": "string"}}}}'
    )
    draft = generate_tool_draft(FakeProvider(content), "nmap port scanner")
    assert draft["name"] == "nmap"
    assert draft["command"] == ["nmap", "{target}"]


def test_generate_tool_draft_no_json():
    with pytest.raises(ValueError):
        generate_tool_draft(FakeProvider("no json here"), "x")


def test_generate_tool_draft_fetches_github_blob(monkeypatch):
    monkeypatch.setattr("lattice_ai.importer._fetch_text", lambda url, timeout=10.0: "#!/bin/sh\nnmap -sV {target}\n")
    captured = {}

    class RecordingProvider:
        def chat(self, messages, tools):
            captured["prompt"] = messages[0]["content"]
            return {"content": '{"name":"x","description":"d","runner":"cli","command":["nmap","{target}"],"parameters":{}}', "tool_calls": []}

    draft = generate_tool_draft(RecordingProvider(), "https://github.com/a/b/blob/main/scan.sh")
    assert "nmap -sV {target}" in captured["prompt"]
    assert draft["name"] == "x"


def test_generate_tool_draft_fetches_repo_readme(monkeypatch):
    def fake_fetch(url, timeout=10.0):
        if url.endswith("/main/README.md"):
            return "# Usage\nnuclei -u {target}"
        return None

    monkeypatch.setattr("lattice_ai.importer._fetch_text", fake_fetch)
    captured = {}

    class RecordingProvider:
        def chat(self, messages, tools):
            captured["prompt"] = messages[0]["content"]
            return {"content": '{"name":"x","description":"d","runner":"cli","command":["nuclei","{target}"],"parameters":{}}', "tool_calls": []}

    generate_tool_draft(RecordingProvider(), "https://github.com/owner/repo")
    assert "nuclei -u {target}" in captured["prompt"]
