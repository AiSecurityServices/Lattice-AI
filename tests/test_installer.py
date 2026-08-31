"""Installer tests (T-U4): registry-driven installs, pinned versions, dry_run."""
from lattice_ai import toolchain_registry as tcr
from lattice_ai.installer import REQUIRED_VULN_TOOLS, install_toolchain


def test_required_vuln_tools_legacy_constant():
    assert REQUIRED_VULN_TOOLS == ["nuclei", "sqlmap", "dalfox"]


def test_dry_run_uses_pinned_go_command():
    res = install_toolchain(["subfinder"], dry_run=True)
    item = res[0]
    assert item["status"] == "installed"
    assert item["detail"] == (
        "would run: go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@v2.6.7"
    )
    assert "@latest" not in item["detail"]


def test_dry_run_sqlmap_pip_branch_from_registry(monkeypatch):
    import lattice_ai.installer as installer

    monkeypatch.setattr(installer, "find_real_executable", lambda name: None)
    res = install_toolchain(["sqlmap"], dry_run=True)
    item = res[0]
    assert item["status"] == "installed"
    assert "pip install sqlmap" in item["detail"]


def test_dry_run_all_registry_tools_produce_commands(monkeypatch):
    import lattice_ai.installer as installer

    monkeypatch.setattr(installer, "find_real_executable", lambda name: None)
    names = [e.name for e in tcr.load_registry() if e.install_primary]
    res = install_toolchain(names, dry_run=True)
    assert len(res) == len(names)
    for item in res:
        assert item["status"] == "installed"
        assert item["detail"].startswith("would run:")
        assert "@latest" not in item["detail"]


def test_nmap_manual_install_returns_hint():
    res = install_toolchain(["nmap"], dry_run=True)
    item = res[0]
    assert item["status"] == "manual"
    assert "nmap.org" in item["detail"]


def test_unknown_tool_skipped():
    res = install_toolchain(["definitely-not-a-tool"], dry_run=True)
    assert res[0]["status"] == "skipped"


def test_already_installed_reports_version(monkeypatch):
    import lattice_ai.installer as installer

    monkeypatch.setattr(installer, "find_real_executable", lambda name: "C:/go/bin/subfinder.exe")
    monkeypatch.setattr(tcr, "registry_version", lambda entry: "2.6.7")
    res = install_toolchain(["subfinder"], dry_run=True)
    item = res[0]
    assert item["status"] == "already_installed"
    assert item["version"] == "2.6.7"


def test_successful_go_install_captures_version(monkeypatch):
    import lattice_ai.installer as installer

    monkeypatch.setattr(installer, "find_real_executable", lambda name: None)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "C:/go/bin/go.exe" if name == "go" else None)
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **kw: __import__("subprocess").CompletedProcess(a[0] if a else [], 0, stdout="", stderr=""))
    monkeypatch.setattr(tcr, "registry_version", lambda entry: "2.6.7")
    res = install_toolchain(["subfinder"], dry_run=False)
    item = res[0]
    assert item["status"] == "installed"
    assert item["version"] == "2.6.7"


def test_failed_go_install_reports_stderr(monkeypatch):
    import lattice_ai.installer as installer

    monkeypatch.setattr(installer, "find_real_executable", lambda name: None)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "C:/go/bin/go.exe" if name == "go" else None)
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **kw: __import__("subprocess").CompletedProcess([], 1, stdout="", stderr="go: build failed"))
    res = install_toolchain(["nuclei"], dry_run=False)
    assert res[0]["status"] == "failed"
    assert "build failed" in res[0]["detail"]


def test_go_install_with_allow_latest_unlocks(monkeypatch):
    import lattice_ai.installer as installer

    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return __import__("subprocess").CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(installer, "find_real_executable", lambda name: None)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "go" if name == "go" else None)
    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    monkeypatch.setattr(tcr, "registry_version", lambda entry: None)
    monkeypatch.setattr(installer, "_go_bin_dir", lambda: "")

    install_toolchain(["subfinder"], dry_run=False, allow_latest=True)
    assert captured["argv"] == ["go", "install", "github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"]
    install_toolchain(["subfinder"], dry_run=False, allow_latest=False)
    assert captured["argv"] == ["go", "install", "github.com/projectdiscovery/subfinder/v2/cmd/subfinder@v2.6.7"]
