from dataclasses import dataclass
from typing import Any

@dataclass
class WorkflowRuntimeInput:
    case_id: int
    workflow_code: str
    workflow_config: dict[str, Any]