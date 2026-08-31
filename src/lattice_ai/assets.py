import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


KINDS = ("domain", "subdomain", "ip", "port", "service", "technology", "endpoint")
RELATIONS = ("resolves_to", "has_port", "runs", "uses", "links_to")


@dataclass
class Asset:
    id: str
    kind: str
    value: str
    natural_key: str
    source_run_id: str = ""
    source_tool: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""


@dataclass
class AssetRelation:
    id: str
    from_asset: str
    to_asset: str
    relation: str
    evidence_ids: list[str] = field(default_factory=list)
    created_at: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def natural_key(kind: str, value: str) -> str:
    return f"{kind}:{value.strip().lower()}"


class AssetStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets_file = self.root / "assets.json"
        self.relations_file = self.root / "relations.json"
        self._assets = self._load(self.assets_file, [])
        self._relations = self._load(self.relations_file, [])

    def _load(self, path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return default

    def _save(self):
        self.assets_file.write_text(json.dumps(self._assets, ensure_ascii=False, indent=2), encoding="utf-8")
        self.relations_file.write_text(json.dumps(self._relations, ensure_ascii=False, indent=2), encoding="utf-8")

    def _find_asset(self, key):
        return next((a for a in self._assets if a["natural_key"] == key), None)

    def upsert_asset(self, *, kind, value, source_run_id="", source_tool="", evidence_id="", session_id=""):
        if kind not in KINDS:
            raise ValueError(f"unknown asset kind: {kind}")
        key = natural_key(kind, value)
        now = now_iso()
        existing = self._find_asset(key)
        if existing:
            if evidence_id and evidence_id not in existing["evidence_ids"]:
                existing["evidence_ids"].append(evidence_id)
            if session_id and not existing.get("session_id"):
                existing["session_id"] = session_id
            existing["last_seen"] = now
            if source_run_id:
                existing["source_run_id"] = source_run_id
            if source_tool:
                existing["source_tool"] = source_tool
            self._save()
            return existing
        asset = {
            "id": "ast_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10],
            "kind": kind,
            "value": value.strip(),
            "natural_key": key,
            "session_id": session_id,
            "source_run_id": source_run_id,
            "source_tool": source_tool,
            "evidence_ids": [evidence_id] if evidence_id else [],
            "first_seen": now,
            "last_seen": now,
        }
        self._assets.append(asset)
        self._save()
        return asset

    def upsert_relation(self, from_asset, to_asset, relation, evidence_id=""):
        if relation not in RELATIONS:
            raise ValueError(f"unknown relation: {relation}")
        existing = next(
            (r for r in self._relations if r["from_asset"] == from_asset and r["to_asset"] == to_asset and r["relation"] == relation),
            None,
        )
        if existing:
            if evidence_id and evidence_id not in existing["evidence_ids"]:
                existing["evidence_ids"].append(evidence_id)
                self._save()
            return existing
        rel = {
            "id": "rel_" + uuid.uuid4().hex[:10],
            "from_asset": from_asset,
            "to_asset": to_asset,
            "relation": relation,
            "evidence_ids": [evidence_id] if evidence_id else [],
            "created_at": now_iso(),
        }
        self._relations.append(rel)
        self._save()
        return rel

    def list_assets(self, kind=None, query="", run_id="", session_id=""):
        out = self._assets
        if kind:
            out = [a for a in out if a["kind"] == kind]
        if query:
            q = query.lower()
            out = [a for a in out if q in a["value"].lower() or q in a["kind"].lower()]
        if run_id:
            out = [a for a in out if a["source_run_id"] == run_id]
        if session_id:
            out = [a for a in out if a.get("session_id") == session_id]
        return out

    def list_relations(self):
        return list(self._relations)

    def graph(self, root_asset_id="", limit=200, session_id=""):
        scoped = self._assets
        if session_id:
            scoped = [a for a in scoped if a.get("session_id", "") == session_id]
        if root_asset_id:
            rels = [r for r in self._relations if r["from_asset"] == root_asset_id or r["to_asset"] == root_asset_id]
            ids = {root_asset_id}
            for r in rels:
                ids.add(r["from_asset"])
                ids.add(r["to_asset"])
            nodes = [a for a in scoped if a["id"] in ids]
            edges = rels
        else:
            nodes = scoped[:limit]
            ids = {a["id"] for a in nodes}
            edges = [r for r in self._relations if r["from_asset"] in ids and r["to_asset"] in ids][:limit]
        return {"nodes": nodes, "edges": edges}
