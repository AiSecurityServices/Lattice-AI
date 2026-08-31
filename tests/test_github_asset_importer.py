from lattice_ai.github_asset_importer import preview_asset_import


def test_local_skill_path_returns_skill_preview(tmp_path):
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("# Recon\n1. Find subdomains", encoding="utf-8")
    preview = preview_asset_import(None, str(skill_file))
    assert preview.source == str(skill_file)
    assert any(a["type"] == "skill" for a in preview.assets)
