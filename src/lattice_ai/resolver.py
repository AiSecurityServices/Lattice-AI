import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path


TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".js", ".ts", ".go", ".rs", ".java", ".yaml", ".yml",
    ".json", ".toml", ".sh", ".html", ".css", ".sql", ".proto", ".graphql",
}
MANIFEST_NAMES = {
    "README.md", "SKILL.md", "go.mod", "package.json", "pyproject.toml",
    "Cargo.toml", "requirements.txt", "Makefile", "Dockerfile", "docker-compose.yml",
}
IGNORED_PARTS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv"}


@dataclass
class ProjectFile:
    path: str
    size: int
    kind: str


@dataclass
class ProjectSnapshot:
    root: str
    files: list[ProjectFile]


def _kind(path: str, name: str) -> str:
    if name in MANIFEST_NAMES:
        return "manifest"
    if name.upper() == "SKILL.MD":
        return "doc"
    suffix = Path(name).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return "source"
    return "unknown"


def _scan_dir(root: Path, cap: int = 200) -> list[ProjectFile]:
    files: list[ProjectFile] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in IGNORED_PARTS for part in p.parts):
            continue
        rel = str(p.relative_to(root))
        kind = _kind(rel, p.name)
        if kind == "unknown":
            continue
        files.append(ProjectFile(rel, p.stat().st_size, kind))
        if len(files) >= cap:
            break
    return files


def _fetch(url: str, timeout: float = 12.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "lattice-ai"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def resolve_source(source: str, mode: str) -> ProjectSnapshot:
    source = source.strip()
    if mode == "path":
        path = Path(source).expanduser()
        if path.is_dir():
            return ProjectSnapshot(str(path), _scan_dir(path))
        if path.is_file():
            return ProjectSnapshot(str(path), [ProjectFile(path.name, path.stat().st_size, _kind(path.name, path.name))])
        raise FileNotFoundError(f"路径不存在: {source}")
    if mode == "url":
        if re.search(r"github\.com/[^/\s]+/[^/\s]+", source):
            match = re.search(r"github\.com/([^/\s]+)/([^/\s]+)", source)
            owner, repo = match.group(1), match.group(2)
            for branch in ("main", "master"):
                for fname in ("README.md", "SKILL.md"):
                    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{fname}"
                    try:
                        body = _fetch(url)
                    except Exception:
                        continue
                    return ProjectSnapshot(source, [ProjectFile(fname, len(body), "manifest" if fname == "README.md" else "doc")])
            raise ValueError("未能获取仓库 README")
        try:
            body = _fetch(source)
        except Exception as exc:
            raise ValueError(f"无法读取该 URL: {source}") from exc
        name = source.split("/")[-1] or "page.md"
        return ProjectSnapshot(source, [ProjectFile(name, len(body), "doc")])
    raise ValueError(f"unsupported mode: {mode}")
