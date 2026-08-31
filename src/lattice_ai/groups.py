import json
from pathlib import Path


EMPTY_GROUPS = {"tool_groups": [], "skill_groups": []}


def _key_for(kind: str) -> str:
    return "tool_groups" if kind == "tool" else "skill_groups"


def next_group_id(kind: str, groups: list[dict]) -> str:
    prefix = "tg" if kind == "tool" else "sg"
    existing = {g.get("id") for g in groups}
    i = 1
    while f"{prefix}-{i:02d}" in existing:
        i += 1
    return f"{prefix}-{i:02d}"


def normalize_group(group: dict) -> dict:
    return {
        "id": str(group.get("id", "")),
        "name": str(group.get("name", "")),
        "members": list(group.get("members", [])),
    }


def normalize_groups(payload) -> dict:
    data = dict(EMPTY_GROUPS)
    if isinstance(payload, dict):
        for key in ("tool_groups", "skill_groups"):
            items = payload.get(key, [])
            data[key] = [normalize_group(g) for g in items if isinstance(g, dict)]
    return data


class AssetGroupStore:
    """Persist tool/skill groups to <project_root>/asset-groups.json."""

    def __init__(self, root):
        self.path = Path(root) / "asset-groups.json"

    def load(self) -> dict:
        if not self.path.exists():
            return dict(EMPTY_GROUPS)
        try:
            return normalize_groups(json.loads(self.path.read_text(encoding="utf-8-sig")))
        except Exception:
            return dict(EMPTY_GROUPS)

    def save(self, data) -> Path:
        normalized = normalize_groups(data)
        self.path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    def create(self, kind: str, name: str) -> dict:
        groups = self.load()
        key = _key_for(kind)
        if any(g["name"] == name for g in groups[key]):
            raise ValueError("分组名称已存在")
        group = {"id": next_group_id(kind, groups[key]), "name": name, "members": []}
        groups[key].append(group)
        self.save(groups)
        return group

    def rename(self, kind: str, group_id: str, name: str) -> dict:
        groups = self.load()
        key = _key_for(kind)
        group = next((g for g in groups[key] if g["id"] == group_id), None)
        if group is None:
            raise KeyError(group_id)
        if any(g["id"] != group_id and g["name"] == name for g in groups[key]):
            raise ValueError("分组名称已存在")
        group["name"] = name
        self.save(groups)
        return group

    def delete(self, kind: str, group_id: str):
        groups = self.load()
        key = _key_for(kind)
        if not any(g["id"] == group_id for g in groups[key]):
            raise KeyError(group_id)
        groups[key] = [g for g in groups[key] if g["id"] != group_id]
        self.save(groups)

    def set_members(self, kind: str, group_id: str, members: list[str]) -> dict:
        groups = self.load()
        key = _key_for(kind)
        group = next((g for g in groups[key] if g["id"] == group_id), None)
        if group is None:
            raise KeyError(group_id)
        group["members"] = list(dict.fromkeys(members))
        self.save(groups)
        return group
