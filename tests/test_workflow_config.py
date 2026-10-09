"""
Checks on the workflow config (app/workflow_configs/workflows.json): its
structure, the properties every role, workflow, step and field must have,
and that it is consistent with itself and with the code that relies on it.

No database needed. A failure names the workflow, step and field, e.g.
"bng_development_v1.gain_condition: next 'gain_plan_submision' is not a step".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.models import bng as bng_model
from app.models.lookup_registry import LOOKUP_REGISTRY
from app.services import bng_finance, bng_payload
from app.services.nbs_links import LOOKUP_FILTERS
from app.services.workflow_roles import validate_role_config
from app.workflows.activity_registry import ACTIVITY_REGISTRY
from app.workflows.bng_activities import BNG_FORM_STEPS

APP_DIR = Path(__file__).resolve().parents[1] / "app"
CONFIG_PATH = APP_DIR / "workflow_configs" / "workflows.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
ROLES = CONFIG["roles"]
WORKFLOWS = CONFIG["workflows"]

FINANCING = ("private_lending_v1", "use_case_2_v1")
BNG = (bng_model.BNG_HABITAT_BANK_WORKFLOW, bng_model.BNG_DEVELOPMENT_WORKFLOW)

CODE = re.compile(r"^[a-z][a-z0-9_]*$")

STEP_REQUIRED = {"title", "activity", "next", "ui_mode", "submit_mode", "fields", "roles", "allow_on_behalf"}
STEP_OPTIONAL = {"stage", "actor", "next_if", "approval"}
UI_MODES = {"form", "assignment_table", "location_table", "file_form", "habitat_table", "bng_metric", "bng_allocation"}
SUBMIT_MODES = {"json", "multipart"}

FIELD_REQUIRED = {"name", "display_name", "type"}
FIELD_OPTIONAL = {
    "required", "help_text", "default", "options", "options_source", "filter_by", "describe_options",
    "content", "row_fields", "entry_help_text", "phase",
}
FIELD_TYPES = {
    "text", "textarea", "number", "select", "checkbox", "date", "file", "content",
    "assignment_table", "location_table", "habitat_table", "bng_allocation",
}
# A step whose ui_mode isn't "form" holds one field of the matching type (or
# none, for bng_metric).
UI_MODE_FIELD = {
    "assignment_table": "assignment_table",
    "location_table": "location_table",
    "habitat_table": "habitat_table",
    "bng_allocation": "bng_allocation",
}
# Lookup filters the API accepts: (lookup, parent field).
ALLOWED_FILTERS = set(LOOKUP_FILTERS) | {("intermediary_function", "intermediary_id")}


def _steps():
    for code, workflow in WORKFLOWS.items():
        for step_code, step in workflow["steps"].items():
            yield code, step_code, step


def _fields(step):
    for field in step["fields"]:
        yield field
        yield from field.get("row_fields", [])


def _order(workflow) -> list[str]:
    """The steps along `next` from the start step."""
    order, step_code = [], workflow["start_step"]
    while step_code is not None:
        assert step_code not in order, f"{workflow['code']}: `next` loops back to {step_code}"
        order.append(step_code)
        step_code = workflow["steps"][step_code]["next"]
    return order


def _field(workflow_code, step_code, name):
    return next(f for f in WORKFLOWS[workflow_code]["steps"][step_code]["fields"] if f["name"] == name)


def _option_values(field) -> list:
    return [option["value"] for option in field.get("options", [])]


STEP_IDS = [f"{code}.{step_code}" for code, step_code, _ in _steps()]


# ---------- top level and roles ----------

def test_top_level_keys():
    assert set(CONFIG) == {"roles", "workflows"}


def test_the_code_accepts_the_role_config():
    validate_role_config(CONFIG)


@pytest.mark.parametrize("code", list(ROLES))
def test_role_definition(code):
    role = ROLES[code]
    assert CODE.match(code), code
    assert set(role) == {"label", "description"}, f"{code}: keys {sorted(role)}"
    assert role["label"].strip() == role["label"] != ""
    assert role["description"].strip().endswith("."), f"{code}: description should be a sentence"


def test_role_labels_are_unique():
    labels = [role["label"] for role in ROLES.values()]
    assert len(labels) == len(set(labels))


def test_every_role_is_used():
    used = {role for workflow in WORKFLOWS.values() for role in workflow["roles"]}
    assert set(ROLES) == used, f"unused roles: {sorted(set(ROLES) - used)}"


# ---------- workflows ----------

@pytest.mark.parametrize("code", list(WORKFLOWS))
def test_workflow_definition(code):
    workflow = WORKFLOWS[code]
    assert set(workflow) == {"code", "name", "start_step", "roles", "creator_role", "steps"}, sorted(workflow)
    assert workflow["code"] == code
    assert workflow["name"].strip()
    assert workflow["roles"] and len(workflow["roles"]) == len(set(workflow["roles"]))
    assert set(workflow["roles"]) <= set(ROLES)
    assert workflow["creator_role"] in workflow["roles"]
    assert workflow["start_step"] == "consent"
    assert workflow["steps"], f"{code}: no steps"


def test_workflow_names_are_unique():
    names = [workflow["name"] for workflow in WORKFLOWS.values()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("code", list(WORKFLOWS))
def test_steps_are_listed_in_order_and_all_reachable(code):
    workflow = WORKFLOWS[code]
    order = _order(workflow)
    # Branches (next_if) only skip ahead along the main path.
    assert order == list(workflow["steps"]), (
        f"{code}: steps should be listed in the order `next` visits them: {order}"
    )


@pytest.mark.parametrize("code", list(WORKFLOWS))
def test_every_workflow_role_has_a_step(code):
    workflow = WORKFLOWS[code]
    with_steps = {role for step in workflow["steps"].values() for role in step["roles"]}
    # Funders and intermediaries view financing projects; they complete no step.
    viewers = {"funder", "intermediary"} if code in FINANCING else set()
    assert set(workflow["roles"]) - viewers == with_steps


# ---------- steps ----------

@pytest.mark.parametrize("code,step_code,step", list(_steps()), ids=STEP_IDS)
def test_step_definition(code, step_code, step):
    where = f"{code}.{step_code}"
    workflow = WORKFLOWS[code]
    assert CODE.match(step_code), where
    assert STEP_REQUIRED <= set(step), f"{where}: missing {sorted(STEP_REQUIRED - set(step))}"
    assert set(step) <= STEP_REQUIRED | STEP_OPTIONAL, f"{where}: unknown {sorted(set(step) - STEP_REQUIRED - STEP_OPTIONAL)}"
    assert step["title"].strip() == step["title"] != ""
    assert step["activity"] in ACTIVITY_REGISTRY, f"{where}: activity {step['activity']} isn't registered"
    assert step["ui_mode"] in UI_MODES, f"{where}: ui_mode {step['ui_mode']}"
    assert step["submit_mode"] in SUBMIT_MODES, f"{where}: submit_mode {step['submit_mode']}"
    assert isinstance(step["allow_on_behalf"], bool), where
    assert step["next"] is None or step["next"] in workflow["steps"], f"{where}: next '{step['next']}' is not a step"
    assert step["next"] != step_code, where

    roles = step["roles"]
    assert roles and len(roles) == len(set(roles)), f"{where}: roles {roles}"
    assert set(roles) <= set(workflow["roles"]), f"{where}: roles {roles} not in the workflow's {workflow['roles']}"

    fields = [field["name"] for field in step["fields"]]
    assert len(fields) == len(set(fields)), f"{where}: duplicate field names"
    has_file = any(field["type"] == "file" for field in step["fields"])
    assert (step["submit_mode"] == "multipart") == has_file, f"{where}: multipart is for file uploads"
    assert (step["ui_mode"] == "file_form") == has_file, f"{where}: file_form is for file uploads"

    if step["ui_mode"] in UI_MODE_FIELD:
        assert [f["type"] for f in step["fields"]] == [UI_MODE_FIELD[step["ui_mode"]]], (
            f"{where}: a {step['ui_mode']} step holds one {UI_MODE_FIELD[step['ui_mode']]} field"
        )
    else:
        assert not {f["type"] for f in step["fields"]} & set(UI_MODE_FIELD.values()), (
            f"{where}: table fields need their own ui_mode"
        )


@pytest.mark.parametrize("code,step_code,step", list(_steps()), ids=STEP_IDS)
def test_step_titles_are_unique_in_a_workflow(code, step_code, step):
    titles = [s["title"] for s in WORKFLOWS[code]["steps"].values()]
    assert titles.count(step["title"]) == 1, f"{code}.{step_code}: title '{step['title']}' is used twice"


@pytest.mark.parametrize("code,step_code,step", [s for s in _steps() if "next_if" in s[2]], ids=lambda v: v if isinstance(v, str) else "")
def test_next_if_branches(code, step_code, step):
    where = f"{code}.{step_code}"
    order = list(WORKFLOWS[code]["steps"])
    fields = {field["name"]: field for field in step["fields"]}
    assert isinstance(step["next_if"], list) and step["next_if"], where
    for rule in step["next_if"]:
        assert set(rule) == {"field", "equals", "next"}, f"{where}: rule {rule}"
        field = fields.get(rule["field"])
        assert field is not None, f"{where}: next_if field {rule['field']} isn't on the step"
        assert field.get("required") and field["type"] == "select", f"{where}: next_if needs a required select"
        assert rule["equals"] in _option_values(field), f"{where}: '{rule['equals']}' isn't an option"
        assert rule["next"] in order, f"{where}: next_if goes to unknown step {rule['next']}"
        assert order.index(rule["next"]) > order.index(step["next"]), f"{where}: next_if should skip ahead"


@pytest.mark.parametrize("code,step_code,step", [s for s in _steps() if "approval" in s[2]], ids=lambda v: v if isinstance(v, str) else "")
def test_approval_steps(code, step_code, step):
    where = f"{code}.{step_code}"
    steps = WORKFLOWS[code]["steps"]
    order = list(steps)
    approval = step["approval"]
    assert set(approval) == {"reject_to", "reject_label"}, f"{where}: {approval}"
    target = approval["reject_to"]
    assert target in steps and order.index(target) < order.index(step_code), f"{where}: must reject back to an earlier step"
    assert approval["reject_label"] == steps[target]["title"], f"{where}: reject_label should be '{steps[target]['title']}'"
    # A rejection goes back to someone else's step: the approver is a different party.
    assert not set(step["roles"]) & set(steps[target]["roles"]), f"{where}: approvers also own {target}"
    # Approvals are decisions: nobody records them on the approver's behalf.
    assert step["allow_on_behalf"] is False, f"{where}: an approval can't be recorded on behalf"


@pytest.mark.parametrize("code", BNG)
def test_bng_steps_show_their_stage_and_actor(code):
    for step_code, step in WORKFLOWS[code]["steps"].items():
        where = f"{code}.{step_code}"
        assert step.get("stage", "").strip(), f"{where}: no stage"
        # The actor tag names the step's roles, by label, in order.
        expected = ", ".join(ROLES[role]["label"] for role in step["roles"])
        assert step.get("actor") == expected, f"{where}: actor should be '{expected}'"


@pytest.mark.parametrize("code", BNG)
def test_bng_stage_is_the_same_for_a_workflow(code):
    assert len({step["stage"] for step in WORKFLOWS[code]["steps"].values()}) == 1


@pytest.mark.parametrize("code", FINANCING)
def test_financing_steps_show_no_stage_or_actor(code):
    for step_code, step in WORKFLOWS[code]["steps"].items():
        assert "stage" not in step and "actor" not in step, f"{code}.{step_code}"


# ---------- fields ----------

@pytest.mark.parametrize("code,step_code,step", list(_steps()), ids=STEP_IDS)
def test_field_definitions(code, step_code, step):
    for field in _fields(step):
        where = f"{code}.{step_code}.{field.get('name')}"
        assert FIELD_REQUIRED <= set(field), f"{where}: missing {sorted(FIELD_REQUIRED - set(field))}"
        assert set(field) <= FIELD_REQUIRED | FIELD_OPTIONAL, f"{where}: unknown {sorted(set(field) - FIELD_REQUIRED - FIELD_OPTIONAL)}"
        assert CODE.match(field["name"]), where
        assert field["display_name"].strip() == field["display_name"] != "", where
        assert field["type"] in FIELD_TYPES, f"{where}: type {field['type']}"
        if "required" in field:
            assert isinstance(field["required"], bool), where

        if field["type"] == "content":
            assert field.get("content", "").strip(), f"{where}: content field without content"
            assert "required" not in field, f"{where}: content can't be required"
        else:
            assert "content" not in field, where
            assert "required" in field, f"{where}: say whether it's required"
            assert field.get("help_text", "").strip(), f"{where}: no help text"
            assert field["help_text"].strip().endswith((".", ")")), f"{where}: help text should be a sentence"

        _check_options(where, field)
        _check_type_specific(where, field, step)


def _check_options(where, field):
    has_options, has_source = "options" in field, "options_source" in field
    if field["type"] != "select":
        assert not (has_options or has_source or "describe_options" in field or "filter_by" in field), (
            f"{where}: options are for select fields"
        )
        return
    assert has_options != has_source, f"{where}: a select needs either options or options_source"
    if has_options:
        values = _option_values(field)
        assert values and len(values) == len(set(values)), f"{where}: options {values}"
        for option in field["options"]:
            assert set(option) == {"value", "label"} and option["label"].strip(), f"{where}: option {option}"
        assert "describe_options" not in field, f"{where}: describe_options is for lookups"
        if "default" in field:
            assert field["default"] in values, f"{where}: default isn't an option"
    else:
        assert field["options_source"] in LOOKUP_REGISTRY, f"{where}: lookup {field['options_source']} doesn't exist"
    if "describe_options" in field:
        assert field["describe_options"] is True, where


def _check_type_specific(where, field, step):
    siblings = [f["name"] for f in step["fields"]]
    for table in step["fields"]:
        if field in table.get("row_fields", []):
            siblings = [f["name"] for f in table["row_fields"]]

    if "filter_by" in field:
        assert (field["options_source"], field["filter_by"]) in ALLOWED_FILTERS, (
            f"{where}: the API can't filter {field['options_source']} by {field['filter_by']}"
        )
        parent = field["filter_by"]
        assert parent in siblings and siblings.index(parent) < siblings.index(field["name"]), (
            f"{where}: filter_by {parent} must be an earlier field beside it"
        )
    assert ("row_fields" in field) == (field["type"] == "assignment_table"), f"{where}: row_fields are for assignment tables"
    if "row_fields" in field:
        assert field["row_fields"], where
    assert ("phase" in field) == (field["type"] == "habitat_table"), f"{where}: phase is for habitat tables"
    if "phase" in field:
        assert field["phase"] in ("baseline", "proposed"), where
    if "entry_help_text" in field:
        assert field["type"] == "location_table", f"{where}: entry_help_text is for location tables"
        assert all(text.strip() for text in field["entry_help_text"].values()), where
    if "default" in field:
        assert field["type"] in ("select", "checkbox"), f"{where}: default on a {field['type']}"
        if field["type"] == "checkbox":
            assert isinstance(field["default"], bool), where
            assert field["default"] is False, f"{where}: a checkbox must not be ticked for the user"


@pytest.mark.parametrize("code,step_code,step", list(_steps()), ids=STEP_IDS)
def test_a_step_has_something_to_enter(code, step_code, step):
    entered = [f for f in step["fields"] if f["type"] != "content"]
    assert entered or step["ui_mode"] == "bng_metric", f"{code}.{step_code}: nothing to enter"


@pytest.mark.parametrize("code,step_code,step", list(_steps()), ids=STEP_IDS)
def test_date_fields_are_named_date(code, step_code, step):
    # The BNG steps check fields named *_date as ISO dates (bng_activities._check_dates).
    for field in step["fields"]:
        assert (field["type"] == "date") == field["name"].endswith("_date"), f"{code}.{step_code}.{field['name']}"


# ---------- the same step in several workflows ----------

def test_shared_activities_get_the_same_fields():
    """Steps sharing a non-BNG activity save into the same table: same field names and types."""
    by_activity: dict[str, set] = {}
    for code, step_code, step in _steps():
        if step["activity"].startswith("save_bng_") or step["activity"] == "save_supporting_document_step":
            continue
        shape = frozenset((f["name"], f["type"]) for f in step["fields"])
        by_activity.setdefault(step["activity"], set()).add(shape)
    assert all(len(shapes) == 1 for shapes in by_activity.values()), {
        activity: shapes for activity, shapes in by_activity.items() if len(shapes) > 1
    }


# ---------- consent ----------

@pytest.mark.parametrize("code", list(WORKFLOWS))
def test_consent_step(code):
    workflow = WORKFLOWS[code]
    consent = workflow["steps"]["consent"]
    assert consent["activity"] == "save_consent_step"
    # The creator gives consent, for themselves only.
    assert consent["roles"] == [workflow["creator_role"]]
    assert consent["allow_on_behalf"] is False
    names = [field["name"] for field in consent["fields"]]
    assert names == ["disclaimer_text", "disclaimer_acknowledged", "allow_data_sharing"]
    assert _field(code, "consent", "disclaimer_acknowledged")["required"] is True
    sharing = _field(code, "consent", "allow_data_sharing")
    # Wider sharing is a free choice: optional, and not ticked in advance.
    assert sharing["required"] is False and sharing["default"] is False


def test_consent_notice_is_the_same_apart_from_the_bng_note():
    note = " This pathway uses a simplified prototype biodiversity metric and does not establish statutory compliance."
    notices = {code: _field(code, "consent", "disclaimer_text")["content"] for code in WORKFLOWS}
    for code, notice in notices.items():
        assert (note in notice) == (code in BNG), code
    assert len({notice.replace(note, "") for notice in notices.values()}) == 1


# ---------- pathway rules ----------

@pytest.mark.parametrize("code", FINANCING)
def test_only_the_borrower_completes_financing_steps(code):
    for step_code, step in WORKFLOWS[code]["steps"].items():
        assert step["roles"] == ["borrower"], f"{code}.{step_code}"
        assert step["allow_on_behalf"] is False, f"{code}.{step_code}"


def test_financing_step_order():
    assert _order(WORKFLOWS["private_lending_v1"]) == [
        "consent", "basic_info", "location", "financial", "identifiers", "intermediary",
    ]
    assert _order(WORKFLOWS["use_case_2_v1"]) == [
        "consent", "basic_info", "financing_type", "location", "nature_based_solution",
        "funding_requirements", "investment_rationale", "supporting_document",
    ]


def test_bng_decisions_are_not_recorded_on_behalf():
    decisions = {
        bng_model.BNG_HABITAT_BANK_WORKFLOW: {"consent", "feasibility", "legal_security"},
        bng_model.BNG_DEVELOPMENT_WORKFLOW: {"consent", "planning_permission", "gain_condition", "gain_plan_approval"},
    }
    for code, steps in decisions.items():
        for step_code, step in WORKFLOWS[code]["steps"].items():
            assert step["allow_on_behalf"] is (step_code not in steps), f"{code}.{step_code}"


def test_gain_plan_is_submitted_before_approval():
    order = _order(WORKFLOWS[bng_model.BNG_DEVELOPMENT_WORKFLOW])
    assert order.index("gain_condition") + 1 == order.index("gain_plan_submission")
    assert order.index("gain_plan_submission") + 1 == order.index("gain_plan_approval")
    approval = WORKFLOWS[bng_model.BNG_DEVELOPMENT_WORKFLOW]["steps"]["gain_plan_approval"]["approval"]
    assert approval["reject_to"] == "gain_plan_submission"


# ---------- what the code relies on ----------

def test_bng_form_steps_exist_with_their_activity():
    bng_steps = {
        step_code: step
        for code in BNG
        for step_code, step in WORKFLOWS[code]["steps"].items()
    }
    for step_code in BNG_FORM_STEPS + ("hmmp", "unit_pricing", "gain_site_register", "planning_permission", "gain_plan_approval"):
        assert bng_steps[step_code]["activity"] == f"save_bng_{step_code}_step", step_code


def test_bng_activities_are_used():
    used = {step["activity"] for _, _, step in _steps()}
    unused = {name for name in ACTIVITY_REGISTRY if name.startswith("save_bng_")} - used
    assert not unused, f"registered but no step uses them: {sorted(unused)}"


def test_fields_the_bng_code_reads():
    bank, development = bng_model.BNG_HABITAT_BANK_WORKFLOW, bng_model.BNG_DEVELOPMENT_WORKFLOW
    pricing = {f["name"] for f in WORKFLOWS[bank]["steps"][bng_model.BNG_PRICING_STEP]["fields"]}
    assert set(bng_finance.PRICE_FIELDS.values()) <= pricing
    assert set(bng_finance.SHARE_FIELDS.values()) <= pricing
    assert bng_finance.DELIVERY_COST_FIELD in pricing

    eligible = _field(bank, bng_model.BNG_FEASIBILITY_STEP, bng_model.BNG_ELIGIBLE_FIELD)
    assert eligible["required"] and "Yes" in _option_values(eligible)
    assert _field(bank, "hmmp", "management_period_years")["type"] == "number"
    assert _field(bank, "gain_site_register", "register_reference")["required"]

    decision = _field(development, bng_model.PLANNING_PERMISSION_STEP, "decision")
    assert set(bng_model.PERMISSION_GRANTED) <= set(_option_values(decision))
    # Refusal is the approval's Reject, so every option grants permission.
    assert set(_option_values(decision)) == set(bng_model.PERMISSION_GRANTED)

    onsite = WORKFLOWS[development]["steps"][bng_payload.ONSITE_DECISION_STEP]
    assert onsite["next"] == bng_model.BNG_ALLOCATION_STEP
    assert [rule["equals"] for rule in onsite["next_if"]] == [bng_payload.ONSITE_ACHIEVED]
    assert WORKFLOWS[development]["steps"][bng_model.BNG_ALLOCATION_STEP]["fields"][0]["required"] is True


def test_bng_roles_the_code_names_exist():
    roles = {
        bng_model.BNG_HABITAT_BANK_WORKFLOW: set(WORKFLOWS[bng_model.BNG_HABITAT_BANK_WORKFLOW]["roles"]),
        bng_model.BNG_DEVELOPMENT_WORKFLOW: set(WORKFLOWS[bng_model.BNG_DEVELOPMENT_WORKFLOW]["roles"]),
    }
    assert set(bng_model.ALLOCATION_DECIDING_ROLES["habitat_bank"]) <= roles[bng_model.BNG_HABITAT_BANK_WORKFLOW]
    assert set(bng_model.ALLOCATION_DECIDING_ROLES["development"]) <= roles[bng_model.BNG_DEVELOPMENT_WORKFLOW]
    assert set(bng_model.MONITORING_BANK_ROLES) <= roles[bng_model.BNG_HABITAT_BANK_WORKFLOW]
    assert set(bng_model.VERIFIER_ROLES) <= roles[bng_model.BNG_HABITAT_BANK_WORKFLOW]


def test_the_export_knows_every_bng_role():
    concepts = (APP_DIR / "semantic" / "concepts" / "concept-schemes.ttl").read_text(encoding="utf-8")
    for code in BNG:
        for role in WORKFLOWS[code]["roles"]:
            assert f"concept/bng-role/{role}>" in concepts, f"{role} has no concept in concept-schemes.ttl"
