import pytest

from lattice_ai import preferences


def test_load_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(preferences, "_PREFS_FILE", tmp_path / "preferences.json")
    assert preferences.load_preferences() == {"theme": "light", "language": "en"}


def test_save_merges_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(preferences, "_PREFS_FILE", tmp_path / "preferences.json")
    out = preferences.save_preferences({"theme": "dark"})
    assert out == {"theme": "dark", "language": "en"}
    assert preferences.load_preferences() == {"theme": "dark", "language": "en"}


def test_save_invalid_theme_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(preferences, "_PREFS_FILE", tmp_path / "preferences.json")
    with pytest.raises(ValueError):
        preferences.save_preferences({"theme": "neon"})
