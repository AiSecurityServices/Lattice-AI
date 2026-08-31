from lattice_ai.models import Stage, Template
from lattice_ai.persistence import load_template, save_template


def test_save_load_roundtrip(tmp_path):
    t = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a")],
    )
    path = tmp_path / "t.json"
    save_template(t, path)
    assert load_template(path) == t


def test_load_template_tolerates_bom(tmp_path):
    t = Template(id="t", name="n", start="a", stages=[Stage(id="a", name="a")])
    path = tmp_path / "t.json"
    save_template(t, path)
    content = path.read_text(encoding="utf-8")
    path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    assert load_template(path) == t
