from lattice_ai.resolver import ProjectSnapshot, resolve_source


def test_resolve_local_directory(tmp_path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (tmp_path / "data.bin").write_bytes(b"\x00\x01")

    snap = resolve_source(str(tmp_path), "path")
    assert isinstance(snap, ProjectSnapshot)
    paths = [f.path for f in snap.files]
    assert any(p.endswith("main.py") for p in paths)
    assert any(p.endswith("SKILL.md") for p in paths)
    assert not any(p.endswith("data.bin") for p in paths)


def test_resolve_local_file(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("hello", encoding="utf-8")
    snap = resolve_source(str(f), "path")
    assert len(snap.files) == 1
    assert snap.files[0].path.endswith("note.md")


def test_resolve_url_missing_raises(monkeypatch):
    import pytest
    import lattice_ai.resolver as resolver

    def boom(url, timeout=12.0):
        raise OSError("network down")

    monkeypatch.setattr(resolver, "_fetch", boom)
    with pytest.raises(ValueError):
        resolve_source("https://example.com/does-not-exist-xyz", "url")
