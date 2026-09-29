from fastapi import APIRouter
from app.routers import status, case_workflow, lookups, intermediaries, support, risk, bng


api_router = APIRouter()

std_prefix = '/api'

api_router.include_router(status.router,
                          prefix=f"{std_prefix}/status",
                          tags=["API Status"])

api_router.include_router(case_workflow.router,
                          prefix=f"{std_prefix}/case_workflow",
                          tags=["Case Workflow"])


api_router.include_router(lookups.router,
                          prefix=f"{std_prefix}/lookups",
                          tags=["Lookups"])



api_router.include_router(intermediaries.router,
                          prefix=f"{std_prefix}/intermediaries",
                          tags=["Intermediaries"])

api_router.include_router(support.router,
                          prefix=f"{std_prefix}/support",
                          tags=["Support"])

api_router.include_router(risk.router,
                          prefix=f"{std_prefix}/risk",
                          tags=["Risk"])

api_router.include_router(bng.router,
                          prefix=f"{std_prefix}/bng",
                          tags=["Biodiversity Net Gain"])
