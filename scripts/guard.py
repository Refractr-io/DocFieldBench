#!/usr/bin/env python3
"""Refuse files (or a commit message) that contain secrets, absolute home paths, or locally denied patterns.

Generic patterns live here. Project-specific patterns come from a local, untracked `.guard-local` file (one regular
expression per line, `#` starts a comment; a line `@file:PATH` denies, literally, every address-like token in that
local file) and from the `GUARD_DENYLIST` environment variable (newline-separated), so
the patterns themselves never enter the repository.

  python scripts/guard.py              scan tracked and untracked-but-not-ignored files
  python scripts/guard.py --staged     scan the staged version of staged files (pre-commit)
  python scripts/guard.py --message F  scan a commit message file (commit-msg)
Exit status 1 on any hit.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

GENERIC = {
    "api key (sk-...)": r"\bsk-[A-Za-z0-9_-]{20,}",
    "hugging face token": r"\bhf_[A-Za-z0-9]{30,}",
    "github token": r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})",
    "aws access key": r"\bAKIA[0-9A-Z]{16}\b",
    "google api key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "private key": r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "email address": r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "absolute home path": r"(/home/[a-z_][a-z0-9_.-]*/|/Users/[A-Za-z][A-Za-z0-9_.-]*/|[A-Za-z]:\\Users\\)",
}
ROOT = Path(__file__).resolve().parents[1]


def local_patterns():
    pats = {}
    f = ROOT / ".guard-local"
    lines = f.read_text().splitlines() if f.exists() else []
    lines += [x for x in os.environ.get("GUARD_DENYLIST", "").splitlines()]
    for i, line in enumerate(x.strip() for x in lines):
        if line.startswith("@file:"):
            src = Path(line[6:].strip()).expanduser()
            toks = src.read_text().split() if src.exists() else []
            for t in toks:
                if "@" in t:
                    pats[f"denied local value (line {i + 1})"] = re.escape(t.strip("<>()\"'"))
        elif line and not line.startswith("#"):
            pats[f"denied pattern #{i + 1}"] = line
    return pats


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def is_binary(data: bytes):
    return b"\0" in data[:8192]


# public source documents print contact addresses; the build's PII gate checks data/
DATA_EXEMPT = {"email address"}


def scan_text(label, text, patterns, hits):
    for name, rx in patterns.items():
        if name in DATA_EXEMPT and label.startswith("data/"):
            continue
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{label}:{line}: {name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--message", type=Path)
    a = ap.parse_args()
    patterns = {**GENERIC, **local_patterns()}
    compiled = {n: re.compile(p, re.MULTILINE) for n, p in patterns.items()}
    hits: list[str] = []
    if a.message:
        scan_text("commit message", a.message.read_text(errors="replace"), compiled, hits)
    elif a.staged:
        names = [n for n in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").decode().splitlines() if n]
        for n in names:
            data = git("show", f":{n}")
            if not is_binary(data):
                scan_text(n, data.decode(errors="replace"), compiled, hits)
            scan_text("path", n, compiled, hits)
    else:
        names = [n for n in git("ls-files", "-co", "--exclude-standard").decode().splitlines() if n]
        for n in names:
            p = ROOT / n
            if not p.is_file():
                continue
            data = p.read_bytes()
            if not is_binary(data):
                scan_text(n, data.decode(errors="replace"), compiled, hits)
            scan_text("path", n, compiled, hits)
    for h in hits:
        print(h, file=sys.stderr)
    if hits:
        print(f"guard: {len(hits)} hit(s); nothing may be committed until they are gone", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
