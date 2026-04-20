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

        case = Case(
            case_type=workflow_code,
            status="in_progress",
            created_by=user_id,
            updated_by=user_id,
        )
        self.db.add(case)
        await self.db.flush()

        case_id = case.id
        temporal_workflow_id = f"case-{case_id}"

        workflow_definition = await self.db.scalar(
            select(WorkflowDefinition).where(
                WorkflowDefinition.code == workflow_code,
                WorkflowDefinition.version == 1,
            )
        )

        if workflow_definition is None:
            workflow_definition = WorkflowDefinition(
                code=workflow_code,
                version=1,
                name=workflow_code,
                description=f"Auto-created from workflows.json for {workflow_code}",
            )
            self.db.add(workflow_definition)
            await self.db.flush()

        client = await Client.connect(settings.TEMPORAL_ADDRESS)

        runtime_input = WorkflowRuntimeInput(
            case_id=case_id,
            workflow_code=workflow_code,
            workflow_config=workflow_config,
        )

        try:
            handle = await client.start_workflow(
                "ConfigDrivenCaseWorkflow",
                runtime_input,
                id=temporal_workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )
            temporal_run_id = handle.first_execution_run_id
            workflow_status = "in_progress"

        except WorkflowAlreadyStartedError:
            existing_run = await self.db.scalar(
                select(CaseWorkflowRun).where(
                    CaseWorkflowRun.temporal_workflow_id == temporal_workflow_id
                )
            )

            if existing_run is not None:
                await self.db.rollback()
                return existing_run.temporal_workflow_id

            await self.db.rollback()
            raise

        except Exception:
            await self.db.rollback()
            raise

        run = CaseWorkflowRun(
            case_id=case_id,
            workflow_definition_id=workflow_definition.workflow_definition_id,
            temporal_workflow_id=temporal_workflow_id,
            temporal_run_id=temporal_run_id,
            current_step=workflow_config["start_step"],
            status=workflow_status,
        )
        self.db.add(run)

        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return temporal_workflow_id