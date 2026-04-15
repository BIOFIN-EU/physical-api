from __future__ import annotations

import json
from pathlib import Path

class WorkflowNotFoundError(ValueError):
    pass

class WorkflowConfigService:
    def __init__(self) -> None:
        self.config_path = Path(__file__).resolve().parent.parent / "workflow_configs" / "workflows.json"

    def load_all(self) -> dict:
        with self.config_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def get_workflow(self, workflow_code: str) -> dict:
        data = self.load_all()
        workflows = data.get("workflows", {})

        if workflow_code not in workflows:
            raise WorkflowNotFoundError(f"Workflow '{workflow_code}' not found")

        return workflows[workflow_code]