from lattice_ai.analyzer import ProjectModel
from lattice_ai.extractor import extract_assets


def test_extract_assets_maps_by_priority():
    model = ProjectModel(
        tools=[
            {"name": "scan", "type": "cli", "command": ["scan", "{target}"], "parameters": {"type": "object", "properties": {"target": {"type": "string"}}}},
            {"name": "remote", "type": "http_api", "command": ["POST", "https://api.example.com"], "ref": "/run/{id}"},
            {"name": "sdk_fn", "type": "skill", "detail": "internal SDK function"},
        ],
        skills=[{"name": "recon-playbook", "description": "recon", "content": "# Recon", "category": "recon"}],
    )
    tools, skills, imports = extract_assets(model)
    assert any(t.name == "scan" and t.runner == "cli" for t in tools)
    assert any(t.name == "remote" and t.runner == "adapter" and t.adapter == "http_api" for t in tools)
    assert any(s.name == "sdk_fn" for s in skills)
    assert any(s.name == "recon-playbook" for s in skills)
    assert imports


def test_extract_assets_mcp():
    from lattice_ai.analyzer import ProjectModel
    model = ProjectModel(tools=[
        {"name": "mcp_tool", "type": "mcp", "command": ["npx", "-y", "server"], "ref": "do_it"},
    ])
    from lattice_ai.extractor import extract_assets
    tools, _, imports = extract_assets(model)
    assert tools[0].runner == "adapter" and tools[0].adapter == "mcp" and tools[0].ref == "do_it"
    assert imports[0]["status"] == "imported"
