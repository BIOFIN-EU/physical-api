from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from app.core.settings import settings
from app.models.case_data import Case
from app.models.workflow import WorkflowDefinition, CaseWorkflowRun
from app.schemas.workflow_runtime import WorkflowRuntimeInput
from app.services.workflow_config_service import WorkflowConfigService


class WorkflowNotActiveError(Exception):
    pass


class WorkflowRuntimeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def start_workflow(
            self,
            workflow_code: str,
            user_id: UUID,
    ) -> str:
        config_service = WorkflowConfigService()
        workflow_config = config_service.get_workflow(workflow_code)

        if not workflow_config:
            raise ValueError(f"Workflow config not found for code: {workflow_code}")

        start_step = workflow_config.get("start_step")
        if not start_step:
            raise ValueError(
                f"Workflow config for '{workflow_code}' is missing 'start_step'"
            )

        # Step 1:
        # Ensure DB state exists first, so Temporal never starts for a non-existent case.
        try:
            workflow_definition = await self._get_or_create_workflow_definition(
                workflow_code=workflow_code
            )

            case = Case(
                case_type=workflow_code,
                status="in_progress",
                created_by=user_id,
                updated_by=user_id,
            )
            self.db.add(case)

            await self.db.commit()
            await self.db.refresh(case)
        except Exception:
            await self.db.rollback()
            raise

        temporal_workflow_id = f"case-{case.id}"

        runtime_input = WorkflowRuntimeInput(
            case_id=case.id,
            workflow_code=workflow_code,
            workflow_config=workflow_config,
        )

        client = await Client.connect(settings.TEMPORAL_ADDRESS)

        # Step 2:
        # Start Temporal only after the case is persisted.
        try:
            handle = await client.start_workflow(
                "ConfigDrivenCaseWorkflow",
                runtime_input,
                id=temporal_workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )
        except WorkflowAlreadyStartedError as exc:
            # With id=f"case-{case.id}", this should be rare because case.id is new.
            # But if it happens, check whether we already have a DB run row.
            existing_run = await self.db.scalar(
                select(CaseWorkflowRun).where(
                    CaseWorkflowRun.temporal_workflow_id == temporal_workflow_id
                )
            )

            if existing_run is not None:
                if existing_run.status in {"failed", "completed"}:
                    raise WorkflowNotActiveError(
                        f"Existing workflow is {existing_run.status}"
                    ) from exc

                return existing_run.temporal_workflow_id

            # Temporal says the workflow exists, but DB has no active run row.
            # Mark the case failed so the database does not falsely suggest success.
            await self._mark_case_failed(case_id=case.id, user_id=user_id)

            raise WorkflowNotActiveError(
                f"Workflow '{temporal_workflow_id}' already exists in Temporal, "
                "but no active DB run record was found."
            ) from exc

        except Exception:
            await self._mark_case_failed(case_id=case.id, user_id=user_id)
            raise

        # Step 3:
        # Persist or update the workflow run record after Temporal has started.
        try:
            await self._upsert_case_workflow_run(
                case_id=case.id,
                workflow_definition_id=workflow_definition.workflow_definition_id,
                temporal_workflow_id=temporal_workflow_id,
                temporal_run_id=handle.first_execution_run_id,
                current_step=start_step,
                status="in_progress",
            )
        except Exception as exc:
            await self.db.rollback()

            # Important: at this point Temporal has already started.
            # We must not pretend everything is fine.
            raise RuntimeError(
                f"Temporal workflow '{temporal_workflow_id}' started successfully, "
                "but saving the DB run record failed. "
                "The workflow may still be running and should be reconciled."
            ) from exc

        return temporal_workflow_id

    async def _get_or_create_workflow_definition(
            self,
            workflow_code: str,
    ) -> WorkflowDefinition:
        workflow_definition = await self.db.scalar(
            select(WorkflowDefinition).where(
                WorkflowDefinition.code == workflow_code,
                WorkflowDefinition.version == 1,
            )
        )

        if workflow_definition is not None:
            return workflow_definition

        workflow_definition = WorkflowDefinition(
            code=workflow_code,
            version=1,
            name=workflow_code,
            description=f"Auto-created from workflows.json for {workflow_code}",
        )
        self.db.add(workflow_definition)
        await self.db.flush()

        return workflow_definition

    async def _upsert_case_workflow_run(
            self,
            case_id,
            workflow_definition_id,
            temporal_workflow_id: str,
            temporal_run_id: str,
            current_step: str,
            status: str,
    ) -> None:
        existing_run = await self.db.scalar(
            select(CaseWorkflowRun).where(
                CaseWorkflowRun.temporal_workflow_id == temporal_workflow_id
            )
        )

        if existing_run is None:
            run = CaseWorkflowRun(
                case_id=case_id,
                workflow_definition_id=workflow_definition_id,
                temporal_workflow_id=temporal_workflow_id,
                temporal_run_id=temporal_run_id,
                current_step=current_step,
                status=status,
            )
            self.db.add(run)
        else:
            existing_run.case_id = case_id
            existing_run.workflow_definition_id = workflow_definition_id
            existing_run.temporal_run_id = temporal_run_id
            existing_run.current_step = current_step
            existing_run.status = status

        await self.db.commit()

    async def _mark_case_failed(self, case_id, user_id: UUID) -> None:
        try:
            case = await self.db.get(Case, case_id)
            if case is not None:
                case.status = "failed"
                case.updated_by = user_id
                await self.db.commit()
            else:
                await self.db.rollback()
        except Exception:
            await self.db.rollback()
            raise
