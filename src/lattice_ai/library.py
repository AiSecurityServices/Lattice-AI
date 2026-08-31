import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from lattice_ai.models import Skill, Template, Tool, from_dict, to_dict
from lattice_ai.persistence import atomic_write_json, atomic_write_text
from lattice_ai.recipes import tool_to_yaml, yaml_to_tool


def _safe(name: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name)
    return cleaned.strip("._") or "unnamed"


def _write_trash_meta(trash_root: Path, kind: str, name: str, filename: str) -> Path:
    target = trash_root / kind
    target.mkdir(parents=True, exist_ok=True)
    meta_path = target / f"{_safe(name)}.meta.json"
    atomic_write_json(
        meta_path,
        {
            "kind": kind,
            "name": name,
            "filename": filename,
            "deleted_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    return meta_path


def _read_trash_meta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _move_to_trash(source: Path, trash_root: Path, kind: str, name: str) -> dict:
    if not source.exists():
        raise KeyError(name)
    target_dir = trash_root / kind
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.move(str(source), str(target))
    _write_trash_meta(trash_root, kind, name, source.name)
    return _read_trash_meta(target_dir / f"{_safe(name)}.meta.json")


class TemplateStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash_root = self.root / ".trash"

    def _path(self, template_id):
        return self.root / f"{_safe(template_id)}.json"

    def list(self):
        return [self.get(p.stem) for p in sorted(self.root.glob("*.json")) if self.get(p.stem)]

    def get(self, template_id):
        path = self._path(template_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def save(self, template_id, data):
        atomic_write_json(self._path(template_id), data)

    def _history_dir(self, template_id):
        return self.root / ".history" / _safe(template_id)

    def _write_history(self, template_id, version, data):
        d = self._history_dir(template_id)
        atomic_write_json(d / f"{version}.json", data)

    def _write_version_meta(self, template_id, version, lineage: dict | None):
        """Sidecar next to the version file: how this version came to be.
        Kept out of the template dict itself so the schema stays untouched."""
        d = self._history_dir(template_id)
        atomic_write_json(d / f"{version}.meta.json", {
            "version": version,
            "lineage": lineage or {"source": "manual", "ref_id": ""},
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        })

    def _read_version_meta(self, template_id, version) -> dict:
        p = self._history_dir(template_id) / f"{version}.meta.json"
        if not p.exists():
            return {"version": version, "lineage": {"source": "manual", "ref_id": ""}, "saved_at": ""}
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            return {"version": version, "lineage": {"source": "manual", "ref_id": ""}, "saved_at": ""}

    def save_versioned(self, template_id, data, lineage: dict | None = None) -> int:
        current = self.get(template_id)
        base = int(current.get("version", 1)) if current else 1
        if current:
            self._write_history(template_id, base, current)
        new_version = base + 1
        self.save(template_id, {**data, "version": new_version})
        self._write_version_meta(template_id, new_version, lineage)
        return new_version

    def list_history(self, template_id):
        d = self._history_dir(template_id)
        return sorted(int(p.stem) for p in d.glob("*.json") if p.stem.isdigit())

    def list_versions(self, template_id, offset: int = 0, limit: int = 50) -> dict:
        """Paged version list including the live current version, each with
        its lineage so the UI can show the snapshot provenance."""
        current = self.get(template_id)
        current_version = int(current.get("version", 1)) if current else None
        versions = self.list_history(template_id)
        if current_version is not None and current_version not in versions:
            versions.append(current_version)
            versions.sort()
        total = len(versions)
        items = []
        for v in versions[offset:offset + limit]:
            meta = self._read_version_meta(template_id, v)
            items.append({
                "version": v,
                "lineage": meta.get("lineage") or {"source": "manual", "ref_id": ""},
                "saved_at": meta.get("saved_at", ""),
                "current": v == current_version,
            })
        return {"total": total, "offset": offset, "limit": limit, "versions": items}

    def get_version(self, template_id, version) -> dict | None:
        p = self._history_dir(template_id) / f"{version}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8-sig"))
        current = self.get(template_id)
        if current and int(current.get("version", 1)) == version:
            return current  # the live version is not archived yet
        return None

    def get_version_lineage(self, template_id, version) -> dict:
        return self._read_version_meta(template_id, version).get("lineage") or {"source": "manual", "ref_id": ""}

    def rollback(self, template_id, version, lineage: dict | None = None) -> int:
        target = self.get_version(template_id, version)
        if target is None:
            raise KeyError(version)
        # n8n-style: restoring never rewrites history — the target content is
        # copied as a new version on top of the chain.
        return self.save_versioned(
            template_id, target,
            lineage or {"source": "manual", "ref_id": str(version)},
        )

    def delete(self, template_id):
        _move_to_trash(self._path(template_id), self.trash_root, "templates", template_id)

    def trash_list(self):
        base = self.trash_root / "templates"
        if not base.exists():
            return []
        return [_read_trash_meta(p) for p in sorted(base.glob("*.meta.json"))]

    def restore(self, template_id):
        base = self.trash_root / "templates"
        meta_path = base / f"{_safe(template_id)}.meta.json"
        if not meta_path.exists():
            raise KeyError(template_id)
        meta = _read_trash_meta(meta_path)
        shutil.move(str(base / meta["filename"]), str(self.root / meta["filename"]))
        meta_path.unlink(missing_ok=True)

    def purge(self, template_id):
        base = self.trash_root / "templates"
        meta_path = base / f"{_safe(template_id)}.meta.json"
        if meta_path.exists():
            meta = _read_trash_meta(meta_path)
            (base / meta["filename"]).unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)

    def empty_trash(self):
        shutil.rmtree(self.trash_root / "templates", ignore_errors=True)

    def clone(self, template_id, new_id):
        data = self.get(template_id)
        if not data:
            raise KeyError(template_id)
        data = {**data, "id": new_id, "name": f"{data.get('name', template_id)}（副本）"}
        self.save(new_id, data)
        return data

    def rename(self, template_id, name):
        data = self.get(template_id)
        if not data:
            raise KeyError(template_id)
        data["name"] = name
        self.save(template_id, data)
        return data


class ToolStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash_root = self.root / ".trash"

    def list(self):
        out = []
        for p in sorted(self.root.glob("*.yaml")):
            try:
                out.append(to_dict(yaml_to_tool(p.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return out

    def save(self, name, data):
        atomic_write_text(self.root / f"{_safe(name)}.yaml", tool_to_yaml(from_dict(Tool, data)))

    def get(self, name):
        path = self.root / f"{_safe(name)}.yaml"
        if not path.exists():
            return None
        return to_dict(yaml_to_tool(path.read_text(encoding="utf-8")))

    def delete(self, name):
        _move_to_trash(self.root / f"{_safe(name)}.yaml", self.trash_root, "tools", name)

    def trash_list(self):
        base = self.trash_root / "tools"
        if not base.exists():
            return []
        return [_read_trash_meta(p) for p in sorted(base.glob("*.meta.json"))]

    def restore(self, name):
        base = self.trash_root / "tools"
        meta_path = base / f"{_safe(name)}.meta.json"
        if not meta_path.exists():
            raise KeyError(name)
        meta = _read_trash_meta(meta_path)
        shutil.move(str(base / meta["filename"]), str(self.root / meta["filename"]))
        meta_path.unlink(missing_ok=True)

    def purge(self, name):
        base = self.trash_root / "tools"
        meta_path = base / f"{_safe(name)}.meta.json"
        if meta_path.exists():
            meta = _read_trash_meta(meta_path)
            (base / meta["filename"]).unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)

    def empty_trash(self):
        shutil.rmtree(self.trash_root / "tools", ignore_errors=True)


class SkillStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash_root = self.root / ".trash"

    def list(self):
        out = []
        for p in sorted(self.root.glob("*.json")):
            try:
                out.append(to_dict(from_dict(Skill, json.loads(p.read_text(encoding="utf-8-sig")))))
            except Exception:
                continue
        return out

    def save(self, name, data):
        atomic_write_json(self.root / f"{_safe(name)}.json", data)

    def get(self, name):
        path = self.root / f"{_safe(name)}.json"
        if not path.exists():
            return None
        return to_dict(from_dict(Skill, json.loads(path.read_text(encoding="utf-8-sig"))))

    def upsert_many(self, skills: "list[dict]") -> dict:
        """Batch import: skip when an existing skill has identical content,
        update when it differs. Idempotent and re-entrant — returns counts.
        (String annotation: ``def list`` above shadows the builtin inside the
        class body, so ``list[dict]`` would resolve to the method.)"""
        counts = {"created": 0, "updated": 0, "skipped": 0}
        for skill in skills or []:
            name = str(skill.get("name") or "").strip()
            if not name:
                counts["skipped"] += 1
                continue
            existing = self.get(name)
            if existing is not None and self._content_hash(existing.get("content")) == self._content_hash(skill.get("content")):
                counts["skipped"] += 1
                continue
            self.save(name, skill)
            counts["updated" if existing is not None else "created"] += 1
        return counts

    @staticmethod
    def _content_hash(content) -> str:
        return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()

    def delete(self, name):
        _move_to_trash(self.root / f"{_safe(name)}.json", self.trash_root, "skills", name)

    def trash_list(self):
        base = self.trash_root / "skills"
        if not base.exists():
            return []
        return [_read_trash_meta(p) for p in sorted(base.glob("*.meta.json"))]

    def restore(self, name):
        base = self.trash_root / "skills"
        meta_path = base / f"{_safe(name)}.meta.json"
        if not meta_path.exists():
            raise KeyError(name)
        meta = _read_trash_meta(meta_path)
        shutil.move(str(base / meta["filename"]), str(self.root / meta["filename"]))
        meta_path.unlink(missing_ok=True)

    def purge(self, name):
        base = self.trash_root / "skills"
        meta_path = base / f"{_safe(name)}.meta.json"
        if meta_path.exists():
            meta = _read_trash_meta(meta_path)
            (base / meta["filename"]).unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)

    def empty_trash(self):
        shutil.rmtree(self.trash_root / "skills", ignore_errors=True)
