from lattice_ai.library import TemplateStore, ToolStore, SkillStore


def test_template_store_crud(tmp_path):
    store = TemplateStore(tmp_path / "templates")
    store.save("t1", {"id": "t1", "name": "Demo", "start": "a", "stages": [], "transitions": [], "tools": [], "skills": []})
    assert any(t["id"] == "t1" for t in store.list())
    assert store.get("t1")["name"] == "Demo"
    store.delete("t1")
    assert not any(t["id"] == "t1" for t in store.list())


def test_tool_and_skill_stores(tmp_path):
    tools = ToolStore(tmp_path / "tools")
    tools.save("nmap", {"name": "nmap", "description": "scan", "runner": "cli", "command": ["nmap"]})
    assert any(t["name"] == "nmap" for t in tools.list())

    skills = SkillStore(tmp_path / "skills")
    skills.save("recon", {"name": "recon", "description": "recon"})
    assert any(s["name"] == "recon" for s in skills.list())
