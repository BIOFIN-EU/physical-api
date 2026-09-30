"""
JSON-LD export (app/semantic): the files parse, every extension term used is
declared, the export of a project is complete, valid (SHACL) and contains
that project only, and personal data is left out.
"""
from __future__ import annotations

import json
import re
import uuid

import pytest
from pyshacl import validate
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS
from sqlalchemy import text

from app.core.settings import settings
from app.semantic import service
from app.workflows.activities import SessionLocal

from tests.test_bng import (  # noqa: F401 (fixtures)
    _development_needing,
    _priced_bank,
    cases,
    reference,
)
from tests.test_bng_matching import _request

HERE = service.HERE
BIOFINEU = Namespace("https://w3id.org/biofineu/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
SCHEMA = Namespace("https://schema.org/")


def bfx() -> Namespace:
    return Namespace(f"{service.base_iri()}ext#")


def iri(path: str) -> URIRef:
    return URIRef(f"{service.base_iri()}{path}")


def _shacl(graph: Graph) -> None:
    shapes = Graph().parse(data=service.render((HERE / "shapes" / "export-shapes.ttl").read_text()), format="turtle")
    conforms, _, report = validate(graph, shacl_graph=shapes)
    assert conforms, report


# ---------- the files themselves ----------

def test_every_file_parses():
    for path in [*HERE.glob("mappings/*.ttl"), *HERE.glob("ontology/*.ttl"), *HERE.glob("data/*.ttl"), *HERE.glob("shapes/*.ttl")]:
        Graph().parse(data=service.render(path.read_text(), case_id=1), format="turtle")
    json.loads(service.render((HERE / "context.jsonld").read_text()))


def test_every_extension_term_used_is_declared():
    declared = {
        str(s)[len(str(bfx())):]
        for s in Graph().parse(data=service.extension_ontology(), format="turtle").subjects(RDF.type, None)
        if str(s).startswith(str(bfx()))
    }
    used = set()
    for path in [*HERE.glob("mappings/*.ttl"), *HERE.glob("data/*.ttl"), *HERE.glob("shapes/*.ttl")]:
        content = path.read_text()
        used |= set(re.findall(r"\bbfx:(\w+)", content))
        used |= set(re.findall(r"\{\{BASE\}\}ext#(\w+)", content))
        # property names chosen in SQL, e.g. VALUES ('totalFunding', ...): camelCase
        if "ext#{kind}" in content:
            used |= set(re.findall(r"\('([a-z]+[A-Z][A-Za-z]*)',", content))
    assert used - declared == set(), f"not declared in biofin-ext.ttl: {sorted(used - declared)}"


def test_extension_terms_are_labelled():
    ext = Graph().parse(data=service.extension_ontology(), format="turtle")
    for term in ext.subjects(RDF.type, None):
        if str(term).startswith(str(bfx())):
            assert ext.value(term, RDFS.label) is not None, term


def test_base_iri_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "SEMANTIC_ENV", "prd")
    assert service.base_iri() == "https://ontology.prd.biofindashboard.eu/"
    assert "https://ontology.prd.biofindashboard.eu/ext#" in service.extension_ontology()
    monkeypatch.setattr(settings, "SEMANTIC_ENV", "dev")
    assert service.base_iri() == "https://ontology.dev.biofindashboard.eu/"


# ---------- a pathway project ----------

def _lookup(session, table: str, code: str, **extra) -> int:
    columns = {"code": code, "name": code.replace("_", " ").title(), **extra}
    names = ", ".join(columns)
    values = ", ".join(f":{k}" for k in columns)
    session.execute(
        text(f"INSERT INTO case_data.{table} ({names}) VALUES ({values}) ON CONFLICT (code) DO NOTHING"), columns
    )
    return session.execute(text(f"SELECT id FROM case_data.{table} WHERE code = :code"), {"code": code}).scalar_one()


@pytest.fixture()
def pathway_project(cases):  # noqa: F811
    """An NbS pathway project with every section filled in, and a second project."""
    project, other = cases("use_case_2_v1"), cases("use_case_2_v1")
    with SessionLocal() as session:
        nbs_type = _lookup(session, "nbs_types", "test_reforestation")
        proceeds = _lookup(session, "use_of_proceeds", "test_land_purchase")
        specialty = _lookup(session, "operator_specialties", "test_forestry")
        netherlands = session.execute(text("SELECT id FROM case_data.countries WHERE code = 'NL'")).scalar_one()
        for case_id, name in ((project, "Exported project"), (other, "Other project")):
            session.execute(text(
                "INSERT INTO case_data.case_basic_info (case_id, name, high_level_description) VALUES (:c, :n, 'About it')"
            ), {"c": case_id, "n": name})
        session.execute(text(
            "INSERT INTO case_data.case_nature_based_solutions (case_id, nbs_type_id, nbs_description) VALUES (:c, :t, 'Trees')"
        ), {"c": project, "t": nbs_type})
        session.execute(text(
            "INSERT INTO case_data.case_locations (case_id, country_id, location_type, geometry_wkt, area_sqm, area_is_manual, "
            "risk_id, friendly_name) VALUES (:c, :nl, 'polygon', 'POLYGON((5 52, 5.1 52, 5.1 52.1, 5 52))', 1234.5, false, "
            "'risk-abc', 'North field')"
        ), {"c": project, "nl": netherlands})
        session.execute(text(
            "INSERT INTO case_data.case_financials (case_id, loan_amount, currency, use_of_proceeds_id, nature_positive_percentage) "
            "VALUES (:c, 250000, 'EUR', :u, 40)"
        ), {"c": project, "u": proceeds})
        session.execute(text(
            "INSERT INTO case_data.case_funding_requirements (case_id, funding_amount, upfront_costs, currency) VALUES (:c, 900, 300, 'EUR')"
        ), {"c": project})
        session.execute(text(
            "INSERT INTO case_data.operators (case_id, name, operator_specialty_id, email, phone) "
            "VALUES (:c, 'Green Ops', :s, 'ops@example.org', '+31 600000000')"
        ), {"c": project, "s": specialty})
        session.commit()
    yield project, other
    with SessionLocal() as session:
        for table in ("operators", "case_funding_requirements", "case_financials", "case_locations",
                      "case_nature_based_solutions", "case_basic_info"):
            session.execute(text(f"DELETE FROM case_data.{table} WHERE case_id IN (:a, :b)"), {"a": project, "b": other})
        session.commit()


def test_pathway_project_export(pathway_project):
    project, other = pathway_project
    graph = service.project_graph(project)
    p = iri(f"data/project/{project}")

    assert (p, RDF.type, BIOFINEU.NbSProduct) in graph
    assert (p, DCTERMS.title, Literal("Exported project")) in graph

    nbs = graph.value(p, BIOFINEU.isContainedInNbS)
    assert (nbs, RDF.type, BIOFINEU.NbS) in graph
    assert (nbs, BIOFINEU.locatedInNUTSRegion, URIRef("http://data.europa.eu/nuts/code/NL")) in graph
    assert (nbs, BIOFINEU.hasRiskProfile, iri("data/risk-score/risk-abc")) in graph

    site = graph.value(p, bfx().hasSite)
    assert (graph.value(site, bfx().country), SKOS.exactMatch,
            URIRef("http://publications.europa.eu/resource/authority/country/NLD")) in graph
    wkt = graph.value(graph.value(site, GEO.hasGeometry), GEO.asWKT)
    assert str(wkt).startswith("POLYGON") and wkt.datatype == GEO.wktLiteral

    loan = graph.value(p, BIOFINEU.usesFinancialInstrument)
    assert str(graph.value(graph.value(loan, bfx().principalAmount), SCHEMA.value)) == "250000.00"
    purpose = graph.value(p, BIOFINEU.hasFinancingPurpose)
    assert (purpose, RDF.type, URIRef("https://spec.edmcouncil.org/fibo/ontology/FND/GoalsAndObjectives/Objectives/Objective")) in graph

    requirement = graph.value(p, bfx().hasFundingRequirement)
    assert str(graph.value(graph.value(requirement, bfx().upfrontCosts), SCHEMA.value)) == "300.00"

    operator = graph.value(p, BIOFINEU.hasOperator)
    assert str(graph.value(operator, RDFS.label)) == "Green Ops"

    # Nothing of the other project, and no contact details.
    dump = graph.serialize(format="nt")
    assert f"data/project/{other}>" not in dump and "Other project" not in dump
    assert "ops@example.org" not in dump and "600000000" not in dump

    _shacl(graph)


def test_jsonld_document_has_the_project_at_the_top(pathway_project):
    project, _ = pathway_project
    document = service.project_jsonld(project)

    assert document["@id"] == f"data:project/{project}"
    assert document["@context"]["biofineu"] == "https://w3id.org/biofineu/"
    assert document["biofineu:isContainedInNbS"]["@type"] == "biofineu:NbS"
    # Concept schemes are references, not embedded.
    assert document["biofineu:hasFinancingPurpose"]["skos:inScheme"] == {"@id": "concept:use-of-proceeds"}

    # The document is valid JSON-LD for the same data.
    reparsed = Graph().parse(data=json.dumps(document), format="json-ld")
    assert (iri(f"data/project/{project}"), DCTERMS.title, Literal("Exported project")) in reparsed


# ---------- BNG ----------

def test_bng_exports_link_the_allocation_from_both_sides(cases, reference):  # noqa: F811
    bank = _priced_bank(cases, reference, price="100")
    development = _development_needing(cases, reference, 22)
    _request(development, bank, "22")

    dev_graph = service.project_graph(development)
    d = iri(f"data/project/{development}")
    assert (d, RDF.type, bfx().Development) in dev_graph
    allocation = dev_graph.value(d, bfx().hasUnitAllocation)
    assert (allocation, bfx().habitatBankProject, iri(f"data/project/{bank}")) in dev_graph
    assert str(dev_graph.value(allocation, bfx().allocationStatus)) == "requested"
    total = dev_graph.value(allocation, bfx().totalPrice)
    assert str(dev_graph.value(total, SCHEMA.currency)) == "GBP"
    # The bank is referred to, not exported: none of its parcels.
    bank_parcels = {o for o in service.project_graph(bank).objects(iri(f"data/project/{bank}"), bfx().hasHabitatParcel)}
    assert bank_parcels and not bank_parcels & set(dev_graph.subjects())
    _shacl(dev_graph)

    bank_graph = service.project_graph(bank)
    b = iri(f"data/project/{bank}")
    assert (b, RDF.type, bfx().HabitatBank) in bank_graph
    assert (b, bfx().suppliesUnitAllocation, allocation) in bank_graph
    parcel = next(bank_graph.objects(b, bfx().hasHabitatParcel))
    assert (parcel, bfx().sizeUnit, URIRef("http://qudt.org/vocab/unit/HA")) in bank_graph
    _shacl(bank_graph)


def test_personal_step_answers_are_left_out(cases, reference):  # noqa: F811
    bank = _priced_bank(cases, reference)
    with SessionLocal() as session:
        session.execute(text(
            "INSERT INTO case_data.bng_step_data (case_id, step_code, data, created_by, updated_by) "
            "VALUES (:c, 'site_registration', CAST(:d AS jsonb), :u, :u)"
        ), {"c": bank, "u": uuid.uuid4(), "d": json.dumps({
            "landowner_name": "Jane Doe", "contact_email": "jane@example.org", "land_registry_title": "AB123",
        })})
        session.commit()
    dump = service.project_graph(bank).serialize(format="nt")
    assert "AB123" in dump
    assert "Jane Doe" not in dump and "jane@example.org" not in dump
    with SessionLocal() as session:
        session.execute(text("DELETE FROM case_data.bng_step_data WHERE case_id = :c"), {"c": bank})
        session.commit()


def test_unknown_project_exports_nothing():
    assert "@type" not in service.project_jsonld(2_000_000_000)
