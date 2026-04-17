from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

from app.schemas.workflow_runtime import WorkflowRuntimeInput


with workflow.unsafe.imports_passed_through():
    from app.workflows.activities import (
        save_location_step,
        save_financial_step,
        save_identifiers_step,
        save_supporting_document_step,
        update_run_state,
    )


@workflow.defn
class ConfigDrivenCaseWorkflow:
    def __init__(self) -> None:
        self.case_id: int | None = None
        self.workflow_code: str | None = None
        self.workflow_config: dict[str, Any] = {}
        self.current_step: str | None = None
        self.status: str = "running"
        self.validation_errors: dict[str, str] = {}

        self._pending_submission: dict[str, Any] | None = None
        self._submission_ready: bool = False

    @workflow.run
    async def run(self, runtime_input: WorkflowRuntimeInput) -> dict[str, Any]:
        self.case_id = runtime_input.case_id
        self.workflow_code = runtime_input.workflow_code
        self.workflow_config = runtime_input.workflow_config

        self.current_step = self.workflow_config["start_step"]
        self.status = "running"
        self.validation_errors = {}

        await workflow.execute_activity(
            update_run_state,
            args=[self.case_id, self.current_step, self.status],
            start_to_close_timeout=timedelta(seconds=30),
        )

        while self.status == "running":
            await workflow.wait_condition(lambda: self._submission_ready)

            payload = self._pending_submission or {}
            self._pending_submission = None
            self._submission_ready = False

            step_name = self.current_step
            if not step_name:
                self.status = "completed"
                break

            step_config = self.workflow_config["steps"][step_name]

            errors = self._validate_required_fields(step_config, payload)
            if errors:
                self.validation_errors = errors
                continue

            self.validation_errors = {}

            activity_name = step_config["activity"]
            activity_fn = self._get_activity_fn(activity_name)

            try:
                await workflow.execute_activity(
                    activity_fn,
                    args=[self.case_id, payload],
                    start_to_close_timeout=timedelta(seconds=30),
                )
            except ActivityError as e:
                cause = e.cause

                if isinstance(cause, ApplicationError) and cause.type == "ValidationError":
                    self.validation_errors = self._extract_validation_errors(cause)
                    continue

                raise

            next_step = step_config.get("next")

            if next_step:
                self.current_step = next_step
                self.status = "running"
            else:
                self.current_step = None
                self.status = "completed"

            await workflow.execute_activity(
                update_run_state,
                args=[self.case_id, self.current_step or "", self.status],
                start_to_close_timeout=timedelta(seconds=30),
            )

        return {
            "case_id": self.case_id,
            "workflow_code": self.workflow_code,
            "current_step": self.current_step,
            "status": self.status,
        }

    @workflow.query
    def get_state(self) -> dict[str, Any]:
        step_config: dict[str, Any] | None = None

        if self.current_step:
            step_config = self.workflow_config["steps"].get(self.current_step)

        return {
            "case_id": self.case_id,
            "workflow_code": self.workflow_code,
            "current_step": self.current_step,
            "status": self.status,
            "validation_errors": self.validation_errors,
            "step": step_config,
        }

    @workflow.signal
    def submit_step(self, payload: dict[str, Any]) -> None:
        self._pending_submission = payload
        self._submission_ready = True

    def _validate_required_fields(
        self,
        step_config: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, str]:
        errors: dict[str, str] = {}

        for field in step_config.get("fields", []):
            if not field.get("required", False):
                continue

            name = field["name"]
            value = payload.get(name)

            if value is None or (isinstance(value, str) and value.strip() == ""):
                errors[name] = "This field is required"

        return errors

    def _extract_validation_errors(self, err: ApplicationError) -> dict[str, str]:
        details = list(err.details)

        if details and isinstance(details[0], dict):
            first = details[0]
            if all(isinstance(k, str) and isinstance(v, str) for k, v in first.items()):
                return first

        return {"form": str(err)}

    def _get_activity_fn(self, activity_name: str):
        activity_map = {
            "save_location_step": save_location_step,
            "save_financial_step": save_financial_step,
            "save_identifiers_step": save_identifiers_step,
            "save_supporting_document_step": save_supporting_document_step,
        }
        if activity_name not in activity_map:
            raise ValueError(f"Unknown activity: {activity_name}")

        return activity_map[activity_name]