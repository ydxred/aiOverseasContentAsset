"""Inject ``repoName`` into an existing ``remotion_props.json``.

Usage::

    python content_asset_mvp/scripts/inject_repo_name.py <content_id>

Reads ``output/<content_id>/github_meta.json`` for ``full_name`` and rewrites
``output/<content_id>/remotion_props.json`` in place. Used to retrofit the
field into demos that were rendered before media_producer started forwarding
``repo_name`` automatically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: inject_repo_name.py <content_id>", file=sys.stderr)
        return 2
    content_id = sys.argv[1]
    project_root = Path(__file__).resolve().parents[1]
    out_dir = project_root / "output" / content_id
    props_path = out_dir / "remotion_props.json"
    meta_path = out_dir / "github_meta.json"

    if not props_path.is_file():
        print(f"ERR: missing {props_path}", file=sys.stderr)
        return 1
    if not meta_path.is_file():
        print(f"ERR: missing {meta_path}", file=sys.stderr)
        return 1

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    repo_name = (
        meta.get("full_name")
        or (
            f"{meta.get('owner')}/{meta.get('repo')}"
            if meta.get("owner") and meta.get("repo")
            else meta.get("repo") or ""
        )
    )
    if not repo_name:
        print("ERR: github_meta has no full_name/owner/repo", file=sys.stderr)
        return 1

    props = json.loads(props_path.read_text(encoding="utf-8"))
    props["repoName"] = repo_name
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ok: {props_path} now has repoName={repo_name!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
