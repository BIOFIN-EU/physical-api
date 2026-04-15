from temporalio.client import Client

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
        case_type: str = "nature_financing",
        created_by: str | None = None,
    ) -> str:
        config_service = WorkflowConfigService()
        workflow_config = config_service.get_workflow(workflow_code)

        # 1. Create the business case first
        case = Case(
            case_type=case_type,
            status="draft",
            created_by=created_by,
        )
        self.db.add(case)
        await self.db.flush()

        # 2. Find or create workflow definition
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

        # 3. Start Temporal workflow
        client = await Client.connect(settings.TEMPORAL_ADDRESS)

        temporal_workflow_id = f"case-{case.case_id}"

        runtime_input = WorkflowRuntimeInput(
            case_id=case.case_id,
            workflow_code=workflow_code,
            workflow_config=workflow_config,
        )

        handle = await client.start_workflow(
            "ConfigDrivenCaseWorkflow",
            runtime_input,
            id=temporal_workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )

        # 4. Store workflow run metadata
        run = CaseWorkflowRun(
            case_id=case.case_id,
            workflow_definition_id=workflow_definition.workflow_definition_id,
            temporal_workflow_id=temporal_workflow_id,
            temporal_run_id=handle.result_run_id,
            current_step=workflow_config["start_step"],
            status="running",
        )
        self.db.add(run)

        await self.db.commit()

        return temporal_workflow_id