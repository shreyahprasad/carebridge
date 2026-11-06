"""Run files for every stage: the dated file plus `<case_id>-latest.json` for the UI.

Rules (ui/README.md): same JSON as the dated file, validated first, written on every
run in every mode, atomically (temp file + os.replace).
"""
import json
import os
import tempfile
from pathlib import Path


def _atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)  # mkstemp makes 0600; keep the old write_text mode for whoever serves data/runs
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_run(report, out_dir, filename, model_cls):
    """Validate report against model_cls, then write <filename> and <case_id>-latest.json. Returns the dated path."""
    model_cls.model_validate(report)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    path = out / filename
    _atomic(path, text)
    _atomic(out / f'{report["case_id"]}-latest.json', text)
    return path
