"""docfieldbench data: fetch a release and check it.

  docfieldbench data download VERSION [--url URL | --from-file TAR] [--dest data]
  docfieldbench data verify DIR

A release is one tar.gz (tasks, documents, sources, manifest.json, DIVERSITY.md). Every file is checked against the
manifest's sha256, and every task must carry the canary. Nothing is trusted that doesn't verify.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import tempfile
from pathlib import Path

from . import CANARY

RELEASES = None      # set to the release-asset URL pattern ("...{v}...") once the repository's public home exists


def verify(root: Path) -> list[str]:
    man = json.loads((root / "manifest.json").read_text())
    problems = []
    if man.get("canary") != CANARY:
        problems.append("manifest canary mismatch")
    for rel, digest in man["files"].items():
        p = root / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            problems.append(f"sha256 mismatch {rel}")
    extra = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} - set(man["files"]) - {"manifest.json"}
    problems += [f"not in the manifest: {e}" for e in sorted(extra)]
    for f in (root / "tasks").glob("*.json"):
        if json.loads(f.read_text()).get("canary") != CANARY:
            problems.append(f"no canary in {f.name}")
    return problems


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    for m in tar.getmembers():
        target = (dest / m.name).resolve()
        if not str(target).startswith(str(dest.resolve())) or m.issym() or m.islnk():
            raise SystemExit(f"refusing archive member {m.name}")
    try:
        tar.extractall(dest, filter="data")
    except TypeError:                                           # Python < 3.12: members were checked above
        tar.extractall(dest)


def download(version: str, url: str | None, from_file: Path | None, dest: Path) -> int:
    out = dest / version
    if out.exists():
        print(f"{out} exists; verifying it")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            tgz = from_file
            if tgz is None:
                import httpx
                tgz = Path(tmp) / "release.tar.gz"
                if not (url or RELEASES):
                    raise SystemExit("no release URL known yet: pass --url or --from-file")
                with httpx.stream("GET", url or RELEASES.format(v=version), follow_redirects=True, timeout=600) as r:
                    r.raise_for_status()
                    with open(tgz, "wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
            staging = Path(tmp) / "x"
            staging.mkdir()
            with tarfile.open(tgz, "r:gz") as tar:
                _safe_extract(tar, staging)
            inner = next(p for p in staging.iterdir() if p.is_dir()) if not (staging / "manifest.json").exists() \
                else staging
            out.parent.mkdir(parents=True, exist_ok=True)
            inner.rename(out)
    problems = verify(out)
    for p in problems[:20]:
        print("  ", p)
    print(f"{out}: {'verified' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="docfieldbench data", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("version")
    d.add_argument("--url")
    d.add_argument("--from-file", type=Path)
    d.add_argument("--dest", type=Path, default=Path("data"))
    v = sub.add_parser("verify")
    v.add_argument("dir", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "verify":
        problems = verify(a.dir)
        for p in problems[:20]:
            print("  ", p)
        print(f"{a.dir}: {'verified' if not problems else f'{len(problems)} problem(s)'}")
        return 1 if problems else 0
    return download(a.version, a.url, a.from_file, a.dest)
