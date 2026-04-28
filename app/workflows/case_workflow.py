from __future__ import annotations

from collections import deque
from datetime import timedelta
from typing import Any, Callable

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from app.schemas.workflow_runtime import WorkflowRuntimeInput
from app.workflows.activity_registry import ACTIVITY_REGISTRY
from app.workflows.activities import update_run_state


DEFAULT_ACTIVITY_TIMEOUT = timedelta(seconds=30)

DEFAULT_ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=[
        "ValidationError",
        "NotFoundError",
        "ConfigurationError",
    ],
)


@workflow.defn
class ConfigDrivenCaseWorkflow:
    """
    Config-driven Temporal workflow for a multi-step case submission flow.

    Important design rule:
    - Only ApplicationError(type="ValidationError") is treated as user-correctable.
    - Everything else is treated as a system/workflow failure.

    This keeps frontend validation behavior predictable.
    """

    def __init__(self) -> None:
        self.case_id: int | None = None
        self.workflow_code: str | None = None
        self.workflow_config: dict[str, Any] = {}
        self.temporal_workflow_id: str | None = None
        self.current_step: str | None = None
        self.status: str = "draft"
        self.validation_errors: dict[str, str] = {}
        self._submission_queue: deque[dict[str, Any]] = deque()
        self.system_error: str | None = None

    @workflow.run
    async def run(self, runtime_input: WorkflowRuntimeInput) -> dict[str, Any]:
        """
        Run the workflow until completion or unrecoverable failure.
        """
        self.case_id = runtime_input.case_id
        self.workflow_code = runtime_input.workflow_code
        self.workflow_config = runtime_input.workflow_config
        self.temporal_workflow_id = workflow.info().workflow_id

        self._validate_runtime_config()

        self.current_step = self.workflow_config["start_step"]
        self.status = "in_progress"
        self.validation_errors = {}
        self.system_error = None

        await self._persist_state()

        try:
            while self.status == "in_progress":
                await workflow.wait_condition(
                    lambda: len(self._submission_queue) > 0
                )

                payload = self._submission_queue.popleft()

                step_name = self.current_step
                if not step_name:
                    self.status = "completed"
                    break

                step_config = self._get_step_config(step_name)

                errors = self._validate_required_fields(step_config, payload)
                if errors:
                    self.validation_errors = errors
                    self.system_error = None
                    continue

                self.validation_errors = {}
                self.system_error = None

                activity_name = self._get_required_step_value(
                    step_config,
                    "activity",
                    step_name,
                )

                activity_fn = self._get_activity_fn(activity_name)

                try:
                    await workflow.execute_activity(
                        activity_fn,
                        args=[self._require_case_id(), payload],
                        start_to_close_timeout=DEFAULT_ACTIVITY_TIMEOUT,
                        retry_policy=DEFAULT_ACTIVITY_RETRY_POLICY,
                    )

                except ActivityError as exc:
                    cause = exc.cause

                    if (
                        isinstance(cause, ApplicationError)
                        and cause.type == "ValidationError"
                    ):
                        self.validation_errors = self._extract_validation_errors(cause)
                        self.system_error = None
                        continue

                    self.status = "failed"
                    self.system_error = str(exc)
                    await self._persist_state()
                    raise

                next_step = step_config.get("next")

                if next_step:
                    self.current_step = next_step
                    self.status = "in_progress"
                else:
                    self.current_step = None
                    self.status = "completed"

                self.validation_errors = {}
                self.system_error = None

                await self._persist_state()

        except Exception as exc:
            if self.status != "failed":
                self.status = "failed"
                self.system_error = str(exc)
                await self._persist_state()

            raise

        return {
            "case_id": self.case_id,
            "temporal_workflow_id": self.temporal_workflow_id,
            "workflow_code": self.workflow_code,
            "current_step": self.current_step,
            "status": self.status,
        }

    @workflow.query
    def get_state(self) -> dict[str, Any]:
        """
        Return current workflow state for the API/frontend.
        """
        step_config: dict[str, Any] | None = None

        if self.current_step:
            step_config = self.workflow_config.get("steps", {}).get(
                self.current_step
            )

        return {
            "case_id": self.case_id,
            "temporal_workflow_id": self.temporal_workflow_id,
            "workflow_code": self.workflow_code,
            "current_step": self.current_step,
            "status": self.status,
            "validation_errors": self.validation_errors,
            "system_error": self.system_error,
            "step": step_config,
        }

    @workflow.signal
    def submit_step(self, payload: dict[str, Any]) -> None:
        """
        Queue a step submission payload.
        """
        self._submission_queue.append(payload)

    async def _persist_state(self) -> None:
        """
        Persist workflow status/current step to the application database.
        """
        await workflow.execute_activity(
            update_run_state,
            args=[self._require_case_id(), self.current_step, self.status],
            start_to_close_timeout=DEFAULT_ACTIVITY_TIMEOUT,
            retry_policy=DEFAULT_ACTIVITY_RETRY_POLICY,
        )

    def _validate_runtime_config(self) -> None:
        """
        Validate minimal workflow configuration.
        """
        if not isinstance(self.workflow_config, dict):
            self._raise_configuration_error("workflow_config must be a dictionary.")

        start_step = self.workflow_config.get("start_step")
        if not isinstance(start_step, str) or not start_step.strip():
            self._raise_configuration_error(
                "workflow_config.start_step is required."
            )

        steps = self.workflow_config.get("steps")
        if not isinstance(steps, dict) or not steps:
            self._raise_configuration_error(
                "workflow_config.steps must be a non-empty dictionary."
            )

        if start_step not in steps:
            self._raise_configuration_error(
                f"Start step '{start_step}' is not defined in workflow_config.steps."
            )

    def _get_step_config(self, step_name: str) -> dict[str, Any]:
        """
        Get the current step configuration.
        """
        steps = self.workflow_config.get("steps")

        if not isinstance(steps, dict):
            self._raise_configuration_error(
                "workflow_config.steps must be a dictionary."
            )

        step_config = steps.get(step_name)

        if not isinstance(step_config, dict):
            self._raise_configuration_error(
                f"Step '{step_name}' is not configured correctly."
            )

        return step_config

    def _get_required_step_value(
        self,
        step_config: dict[str, Any],
        key: str,
        step_name: str,
    ) -> str:
        """
        Get a required string value from a step configuration.
        """
        value = step_config.get(key)

        if not isinstance(value, str) or not value.strip():
            self._raise_configuration_error(
                f"Step '{step_name}' is missing required config value '{key}'."
            )

        return value

    def _validate_required_fields(
        self,
        step_config: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, str]:
        """
        Validate only fields marked as required in workflow config.

        Deeper type/business validation belongs in the activity layer.
        """
        errors: dict[str, str] = {}

        fields = step_config.get("fields", [])

        if not isinstance(fields, list):
            return {
                "form": "Invalid workflow configuration: fields must be a list."
            }

        for field in fields:
            if not isinstance(field, dict):
                continue

            if not field.get("required", False):
                continue

            name = field.get("name")

            if not isinstance(name, str) or not name:
                continue

            value = payload.get(name)

            if value is None or (isinstance(value, str) and value.strip() == ""):
                errors[name] = "This field is required"

        return errors

    def _extract_validation_errors(self, err: ApplicationError) -> dict[str, str]:
        """
        Extract frontend-safe validation errors from ApplicationError details.
        """
        details = list(err.details)

        if details and isinstance(details[0], dict):
            first = details[0]

            if all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in first.items()
            ):
                return first

        return {"form": str(err)}

    def _get_activity_fn(self, activity_name: str) -> Callable[..., Any]:
        """
        Resolve an activity function from the activity registry.
        """
        activity_fn = ACTIVITY_REGISTRY.get(activity_name)

        if activity_fn is None:
            self._raise_configuration_error(
                f"Unknown activity: {activity_name}"
            )

        return activity_fn

    def _require_case_id(self) -> int:
        """
        Return initialized case ID.
        """
        if self.case_id is None:
            self._raise_configuration_error("case_id is not initialized.")

        return self.case_id

    def _raise_configuration_error(self, message: str) -> None:
        """
        Raise non-retryable workflow configuration error.
        """
        raise ApplicationError(
            message,
            type="ConfigurationError",
            non_retryable=True,
        )