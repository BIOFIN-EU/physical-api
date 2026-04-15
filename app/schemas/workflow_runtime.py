from dataclasses import dataclass


@dataclass
class WorkflowRuntimeInput:
    case_id: int
    workflow_code: str
    workflow_config: dict