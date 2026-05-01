from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArtifactWriter:
    def __init__(self, output_dir: Path, workspace_dir: Path, content_id: str):
        self.output_dir = output_dir / content_id
        self.workspace_dir = workspace_dir / content_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def output_path(self, filename: str) -> Path:
        return self.output_dir / filename

    def workspace_path(self, filename: str) -> Path:
        return self.workspace_dir / filename

    def write_json(self, filename: str, data: dict[str, Any], *, workspace: bool = False) -> Path:
        path = self.workspace_path(filename) if workspace else self.output_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def read_json(self, filename: str, *, workspace: bool = False) -> dict[str, Any]:
        path = self.workspace_path(filename) if workspace else self.output_path(filename)
        return json.loads(path.read_text(encoding="utf-8"))

    def write_markdown(self, filename: str, content: str, *, workspace: bool = False) -> Path:
        path = self.workspace_path(filename) if workspace else self.output_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return path

    def exists(self, filename: str, *, workspace: bool = False) -> bool:
        path = self.workspace_path(filename) if workspace else self.output_path(filename)
        return path.exists()

