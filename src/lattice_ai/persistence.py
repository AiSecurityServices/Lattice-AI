import json
import os
import tempfile
from pathlib import Path

from lattice_ai.models import Template, from_dict, to_dict


def atomic_write_text(path, text: str) -> None:
    """Write text so a crash never leaves a torn file: write to a temp file in
    the same directory, fsync, then atomically replace the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path, data) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def save_template(template: Template, path) -> None:
    atomic_write_json(path, to_dict(template))


def load_template(path) -> Template:
    return from_dict(Template, json.loads(Path(path).read_text(encoding="utf-8-sig")))
