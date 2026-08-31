import yaml

from lattice_ai.models import Tool, from_dict, to_dict


def tool_to_yaml(tool: Tool) -> str:
    return yaml.safe_dump(to_dict(tool), sort_keys=False, allow_unicode=True)


def yaml_to_tool(text: str) -> Tool:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("recipe must be a YAML mapping")
    return from_dict(Tool, data)


# Only truly external CLI tools are seeded as recipes. Recon tools are built in
# process (see lattice_ai.builtins) and are no longer stored as CLI recipes.
BUNDLED_RECIPES = [
    {
        "name": "nuclei",
        "description": "Run nuclei vulnerability scanner",
        "runner": "cli",
        "command": ["nuclei", "-u", "{target}"],
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
    },
    {
        "name": "sqlmap",
        "description": "Test and exploit SQL injection",
        "runner": "cli",
        "command": ["sqlmap", "-u", "{target}", "--batch"],
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
    },
    {
        "name": "dalfox",
        "description": "Detect and verify XSS",
        "runner": "cli",
        "command": ["dalfox", "url", "{target}"],
        "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
    },
]


def load_bundled_recipes() -> list[Tool]:
    return [from_dict(Tool, r) for r in BUNDLED_RECIPES]
