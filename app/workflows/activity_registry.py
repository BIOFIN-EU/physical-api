from app.workflows.activities import (
    save_location_step,
    save_financial_step,
    save_identifiers_step,
    save_supporting_document_step,
    save_basic_info_step,
    save_financing_type_step,
    save_nature_based_solution_step,
    save_funding_requirements_step,
    save_investment_rationale_step,
)

ACTIVITY_REGISTRY = {
    "save_location_step": save_location_step,
    "save_financial_step": save_financial_step,
    "save_identifiers_step": save_identifiers_step,
    "save_supporting_document_step": save_supporting_document_step,
    "save_basic_info_step": save_basic_info_step,
    "save_financing_type_step": save_financing_type_step,
    "save_nature_based_solution_step": save_nature_based_solution_step,
    "save_funding_requirements_step": save_funding_requirements_step,
    "save_investment_rationale_step": save_investment_rationale_step,
}