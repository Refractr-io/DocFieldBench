"""Release packaging: download --from-file extracts and verifies; a tampered file fails."""
import json
import tarfile

from docfieldbench import CANARY, data


def _release(tmp_path):
    root = tmp_path / "v9"
    (root / "tasks").mkdir(parents=True)
    (root / "tasks" / "a.json").write_text(json.dumps({"canary": CANARY, "task_id": "a"}))
    import hashlib
    files = {"tasks/a.json": hashlib.sha256((root / "tasks" / "a.json").read_bytes()).hexdigest()}
    (root / "manifest.json").write_text(json.dumps({"canary": CANARY, "files": files}))
    tgz = tmp_path / "r.tar.gz"
    with tarfile.open(tgz, "w:gz") as t:
        t.add(root, arcname="v9")
    return tgz


def test_download_and_verify(tmp_path):
    tgz = _release(tmp_path)
    assert data.download("v9", None, tgz, tmp_path / "dest") == 0
    (tmp_path / "dest" / "v9" / "tasks" / "a.json").write_text("{}")
    assert data.verify(tmp_path / "dest" / "v9")
