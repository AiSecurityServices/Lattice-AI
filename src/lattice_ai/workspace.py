import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from lattice_ai import approval as approval_module
from lattice_ai.assets import AssetStore
from lattice_ai.db import JsonStore, connect as db_connect
from lattice_ai.groups import AssetGroupStore
from lattice_ai.models import Evidence, Finding, from_dict, to_dict
from lattice_ai.persistence import atomic_write_json, atomic_write_text

logger = logging.getLogger("lattice_ai.workspace")


def safe_name(value: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in value)
    return cleaned.strip("._") or "unnamed"


class Project:
    def __init__(self, project_id: str, root, name: str | None = None):
        self.id = project_id
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.evidence_dir = self.root / "evidence"
        self.findings_dir = self.root / "findings"
        self.settings_file = self.root / "settings.json"
        self.meta_file = self.root / "project.json"
        self.scope_file = self.root / "scope_policy.json"
        self.danger_file = self.root / "danger_policy.json"
        self.approvals_file = self.root / "approvals.json"
        for d in (self.sessions_dir, self.evidence_dir, self.findings_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.name = self._load_name(name)
        self.current_template_id = self._load_current_template_id()
        self._db = db_connect(self.root / "project.db")
        self.runs = JsonStore(self._db, "runs")
        self.evidence = JsonStore(self._db, "evidence")
        self.findings = JsonStore(self._db, "findings")
        self.approvals = JsonStore(self._db, "approvals")
        self.executions = JsonStore(self._db, "stage_executions")
        self._migrate_legacy_json()
        self.settings = self._load_settings()
        self.asset_groups = self._load_asset_groups()
        self.conversations = self._load_conversations()
        self.scope_policy = self._load_json(self.scope_file, {})
        self.danger_policy = self._load_json(self.danger_file, {"level": "lenient", "whitelist": []})
        self.approval_logs = self._load_json(self.approvals_file, [])
        self.assets = AssetStore(self.root)

    def _load_name(self, fallback):
        if self.meta_file.exists():
            try:
                return json.loads(self.meta_file.read_text(encoding="utf-8")).get("name") or fallback or self.id
            except Exception:
                pass
        return fallback or self.id

    def _load_current_template_id(self):
        if self.meta_file.exists():
            try:
                return json.loads(self.meta_file.read_text(encoding="utf-8")).get("current_template_id", "")
            except Exception:
                pass
        return ""

    def close(self) -> None:
        """Release the SQLite handle; required on Windows before the project
        directory can be moved or removed."""
        db = getattr(self, "_db", None)
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
            self._db = None

    def _write_json(self, path, data):
        atomic_write_json(path, data)

    def _read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))

    def _load_json(self, path, default):
        if not path.exists():
            return default
        try:
            return self._read_json(path)
        except Exception:
            return default

    def _write_meta(self):
        self._write_json(self.meta_file, {"id": self.id, "name": self.name, "current_template_id": self.current_template_id})

    def save_meta(self, name):
        self.name = name
        self._write_meta()

    def save_current_template_id(self, template_id):
        self.current_template_id = template_id
        self._write_meta()

    def _migrate_legacy_json(self):
        """One-time import of the pre-SQLite per-file run artifacts.

        Legacy files are read, never removed: the DB becomes the canonical
        store, and the original sessions/evidence/findings files stay on disk
        as a fallback until the user deletes them. Re-runs are safe — every
        write is an upsert keyed by the old in-memory keys.
        """
        meta = JsonStore(self._db, "meta")
        if meta.get("legacy_imported"):
            return
        counts = {}
        if self.sessions_dir.exists():
            counts["runs"] = 0
            for p in sorted(self.sessions_dir.glob("*.json")):
                if p.name.endswith(".state.json"):
                    continue
                try:
                    data = self._read_json(p)
                except Exception as exc:
                    logger.warning("skipping unreadable legacy run %s: %s", p.name, exc)
                    continue
                self.runs[p.stem] = data
                counts["runs"] += 1
        for dirname, directory, store, model in (
            ("evidence", self.evidence_dir, self.evidence, Evidence),
            ("findings", self.findings_dir, self.findings, Finding),
        ):
            if not directory.exists():
                continue
            counts[dirname] = 0
            for p in sorted(directory.glob("*.json")):
                try:
                    item = from_dict(model, self._read_json(p))
                except Exception as exc:
                    logger.warning("skipping unreadable legacy %s file %s: %s", dirname, p.name, exc)
                    continue
                store[item.id or p.stem] = to_dict(item)
                counts[dirname] += 1
        meta["legacy_imported"] = {"migrated_at": datetime.now().isoformat(timespec="seconds"), **counts}

    def save_evidence(self, evidence_id, data):
        self.evidence[evidence_id] = data

    def save_finding(self, finding_id, data):
        self.findings[finding_id] = data

    def save_run(self, run_id, data):
        self.runs[run_id] = data

    def _load_settings(self):
        if self.settings_file.exists():
            try:
                return self._read_json(self.settings_file)
            except Exception:
                pass
        return {}

    def save_settings(self, settings):
        self.settings = settings
        self._write_json(self.settings_file, settings)

    def save_scope_policy(self, policy):
        self.scope_policy = policy
        self._write_json(self.scope_file, policy)

    def save_danger_policy(self, policy):
        self.danger_policy = policy
        self._write_json(self.danger_file, policy)

    def save_approval_decision(self, decision):
        self.approval_logs.append(decision)
        self._write_json(self.approvals_file, self.approval_logs)

    def _load_asset_groups(self):
        return AssetGroupStore(self.root).load()

    def save_asset_groups(self):
        AssetGroupStore(self.root).save(self.asset_groups)

    def _load_conversations(self):
        path = self.root / "conversations.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8-sig")).get("conversations", [])
            except Exception:
                return []
        return []

    def save_conversations(self, conversations):
        self.conversations = conversations
        self._write_json(self.root / "conversations.json", {"conversations": conversations})

    def get_conversation(self, conv_id):
        return next((c for c in self.conversations if c.get("id") == conv_id and not c.get("deleted_at")), None)

    def upsert_conversation(self, conv):
        for i, c in enumerate(self.conversations):
            if c.get("id") == conv.get("id"):
                self.conversations[i] = conv
                self.save_conversations(self.conversations)
                return
        self.conversations.append(conv)
        self.save_conversations(self.conversations)

    def delete_conversation(self, conv_id):
        for conv in self.conversations:
            if conv.get("id") == conv_id:
                conv["deleted_at"] = datetime.now().isoformat(timespec="seconds")
                break
        self.save_conversations(self.conversations)

    def restore_conversation(self, conv_id):
        for conv in self.conversations:
            if conv.get("id") == conv_id:
                conv.pop("deleted_at", None)
                break
        self.save_conversations(self.conversations)

    def trashed_conversations(self):
        return [c for c in self.conversations if c.get("deleted_at")]

    def purge_conversation(self, conv_id):
        self.conversations = [c for c in self.conversations if c.get("id") != conv_id]
        self.save_conversations(self.conversations)

    def empty_trash_conversations(self):
        self.conversations = [c for c in self.conversations if not c.get("deleted_at")]
        self.save_conversations(self.conversations)


class ProjectStore:
    def __init__(self, root, *, seed_settings=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash_root = self.root / ".trash"
        self.seed_settings = seed_settings or {}
        self._projects = {}
        self.current = None
        self._scan()
        if "default" not in self._projects:
            self._create("default", "默认项目")
        if self.current is None:
            self.current = "default"
        self._sync_approval_store()

    def _sync_approval_store(self):
        """Keep durable approval records pointed at the active project's store."""
        project = self._projects.get(self.current)
        if project is not None:
            approval_module.bind_store(project.approvals)

    def _scan(self):
        for d in sorted(self.root.iterdir()):
            if d.is_dir():
                if d.name == ".trash":
                    continue
                try:
                    project = Project(d.name, d)
                    self._projects[project.id] = project
                except Exception as exc:
                    logger.warning("skipping unreadable project %s: %s", d.name, exc)
                    continue

    def _seed(self, project):
        project.save_settings(dict(self.seed_settings))

    def _create(self, project_id, name):
        root = self.root / project_id
        root.mkdir(parents=True, exist_ok=True)
        project = Project(project_id, root, name=name)
        project.save_meta(name)
        self._seed(project)
        self._projects[project_id] = project
        return project

    def _unique_id(self, name):
        base = safe_name(name.lower()) or "project"
        project_id = base
        i = 2
        while project_id in self._projects:
            project_id = f"{base}-{i}"
            i += 1
        return project_id

    def list(self):
        return [{"id": p.id, "name": p.name} for p in self._projects.values()]

    def get(self, project_id):
        return self._projects.get(project_id)

    def active(self):
        return self._projects[self.current]

    def switch(self, project_id):
        if project_id not in self._projects:
            raise KeyError(project_id)
        self.current = project_id
        self._sync_approval_store()

    def create(self, name):
        project = self._create(self._unique_id(name), name)
        return project

    def delete(self, project_id):
        if project_id == self.current:
            raise ValueError("cannot delete the active project")
        if project_id not in self._projects:
            raise KeyError(project_id)
        project = self._projects[project_id]
        project.close()
        target_dir = self.trash_root / "projects"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{project_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.move(str(project.root), str(target))
        meta_path = target_dir / f"{project_id}.meta.json"
        atomic_write_json(
            meta_path,
            {
                "kind": "projects",
                "name": project_id,
                "filename": target.name,
                "deleted_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        del self._projects[project_id]

    def trash_list(self):
        base = self.trash_root / "projects"
        if not base.exists():
            return []
        out = []
        for meta_path in sorted(base.glob("*.meta.json")):
            try:
                out.append(json.loads(meta_path.read_text(encoding="utf-8-sig")))
            except Exception:
                continue
        return out

    def restore_project(self, project_id):
        base = self.trash_root / "projects"
        meta_path = base / f"{project_id}.meta.json"
        if not meta_path.exists():
            raise KeyError(project_id)
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        source = base / meta["filename"]
        target = self.root / project_id
        shutil.move(str(source), str(target))
        meta_path.unlink(missing_ok=True)
        self._projects[project_id] = Project(project_id, target)
        self._sync_approval_store()

    def purge_project(self, project_id):
        base = self.trash_root / "projects"
        meta_path = base / f"{project_id}.meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            shutil.rmtree(base / meta["filename"], ignore_errors=True)
            meta_path.unlink(missing_ok=True)

    def empty_trash(self):
        shutil.rmtree(self.trash_root / "projects", ignore_errors=True)
