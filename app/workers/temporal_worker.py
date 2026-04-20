import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from app.workflows.case_workflow import ConfigDrivenCaseWorkflow
from app.workflows.activities import (
    save_location_step,
    save_financial_step,
    save_identifiers_step,
    save_supporting_document_step,
    update_run_state,
)

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "case-workflow-task-queue")


async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS)
    activity_executor = ThreadPoolExecutor(max_workers=10)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ConfigDrivenCaseWorkflow],
        activities=[
            save_location_step,
            save_financial_step,
            save_identifiers_step,
            save_supporting_document_step,
            update_run_state,
        ],
        activity_executor=activity_executor,
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())