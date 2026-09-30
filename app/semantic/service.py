"""
JSON-LD export of a project, following the BIOFIN-EU ontology
(https://w3id.org/biofineu/) and its dashboard extensions
(ontology/biofin-ext.ttl).

How it works:
1. The R2RML mappings in mappings/ describe how database rows become RDF.
   Their placeholders are filled in: {{BASE}} (the base IRI, from
   SEMANTIC_ENV) and {{CASE_ID}} (so every query reads one project only).
2. Morph-KGC (an R2RML processor) runs them against the database, giving an
   RDF graph; data/concept-schemes.ttl is added to it.
3. The graph is framed as JSON-LD: one document, the project at the top,
   with what it refers to nested inside. Nodes it doesn't refer to (e.g.
   unused concepts) are dropped.

See README.md for where to change what.
"""
from __future__ import annotations

import copy
import json
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from morph_kgc.args_parser import load_config_from_argument
from morph_kgc.constants import RML_TRIPLES_MAP_CLASS
from morph_kgc.data_source import relational_db
from morph_kgc.mapping.mapping_parser import retrieve_mappings
from morph_kgc.materializer import _materialize_mapping_group_to_set
from pyld import jsonld
from rdflib import Graph
from sqlalchemy import create_engine

from app.core.settings import settings

HERE = Path(__file__).parent
MAPPINGS = HERE / "mappings"
EXTENSION_ONTOLOGY = HERE / "ontology" / "biofin-ext.ttl"
STATIC_DATA = HERE / "data" / "concept-schemes.ttl"
CONTEXT_FILE = HERE / "context.jsonld"

BASE_TOKEN = "{{BASE}}"
CASE_TOKEN = "{{CASE_ID}}"


def base_iri() -> str:
    """https://ontology.<dev|prd>.biofindashboard.eu/ (setting SEMANTIC_ENV)."""
    return f"https://ontology.{settings.SEMANTIC_ENV}.biofindashboard.eu/"


def project_iri(case_id: int) -> str:
    return f"{base_iri()}data/project/{int(case_id)}"


def render(text: str, case_id: int | None = None) -> str:
    text = text.replace(BASE_TOKEN, base_iri())
    if case_id is not None:
        # An int, so nothing but digits reaches the SQL.
        text = text.replace(CASE_TOKEN, str(int(case_id)))
    return text


def extension_ontology() -> str:
    """The extension ontology (Turtle) with the base IRI filled in."""
    return render(EXTENSION_ONTOLOGY.read_text())


@lru_cache
def _context_template() -> dict[str, Any]:
    return json.loads(CONTEXT_FILE.read_text())


def context() -> dict[str, Any]:
    """The JSON-LD @context (context.jsonld): prefixes of the vocabularies used."""
    return json.loads(render(json.dumps(_context_template())))


# Morph-KGC (pinned in requirements.txt) is used through its internal steps
# rather than morph_kgc.materialize(), which re-parses every mapping file and
# opens a new database connection per query on every call (about 5 s per
# project). Here the mappings are parsed once per process, keeping the
# {{CASE_ID}} placeholder in their SQL, and the placeholder is filled in per
# export; queries share a small connection pool. Check these two functions
# when upgrading Morph-KGC.


@lru_cache
def _engine(url: str):
    return create_engine(url, pool_size=2, max_overflow=2, pool_pre_ping=True)


def _pooled_connection(config, source_name):
    engine = _engine(config.get_db_url(source_name))
    return engine, engine.dialect.name.upper()


relational_db._relational_db_connection = _pooled_connection

_lock = threading.Lock()


@lru_cache
def _parsed_mappings():
    """(config, rules, function rules), parsed once: the SQL still has {{CASE_ID}}."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for mapping in sorted(MAPPINGS.glob("*.r2rml.ttl")):
            path = Path(tmp) / mapping.name
            path.write_text(render(mapping.read_text()))
            paths.append(str(path))
        config = load_config_from_argument(
            "[CONFIGURATION]\n"
            "logging_level: WARNING\n"
            # SQL NULLs reach Morph-KGC as "None": treat them as missing.
            "na_values: ,None,NULL,null,nan,NaN,<NA>\n"
            "number_of_processes: 1\n"
            "[DataSource]\n"
            f"mappings: {','.join(paths)}\n"
            f"db_url: {settings.sync_database_url}\n"
        )
        rules, function_rules, http_api_rules = retrieve_mappings(config)
    config.set("CONFIGURATION", "http_api_df", http_api_rules.to_csv())
    return config, rules, function_rules


def project_graph(case_id: int) -> Graph:
    """The RDF graph of one project (and the code lists it may refer to)."""
    config, rules, function_rules = _parsed_mappings()
    rules = rules.copy()
    rules["logical_source_value"] = rules["logical_source_value"].str.replace(
        CASE_TOKEN, str(int(case_id)), regex=False
    )
    asserted = rules.loc[rules["triples_map_type"] == RML_TRIPLES_MAP_CLASS]
    triples: set[str] = set()
    with _lock:
        for _, group in asserted.groupby(by="mapping_partition"):
            triples.update(_materialize_mapping_group_to_set(group, rules, function_rules, config, None))

    graph = Graph()
    if triples:
        graph.parse(data=".\n".join(triples) + ".", format="nquads")
    graph.parse(data=render(STATIC_DATA.read_text()), format="turtle")
    return graph


def _scheme_links(node: Any) -> Any:
    """Concepts' skos:inScheme as a plain reference, not the embedded scheme."""
    if isinstance(node, list):
        return [_scheme_links(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key == "skos:inScheme":
            out[key] = (
                [{"@id": v["@id"]} for v in value] if isinstance(value, list)
                else {"@id": value["@id"]} if isinstance(value, dict) and "@id" in value else value
            )
        else:
            out[key] = _scheme_links(value)
    return out


def project_jsonld(case_id: int) -> dict[str, Any]:
    """
    The project as one JSON-LD document: the project node, with the nodes
    it refers to embedded (concept schemes stay references, to keep the
    document short).
    """
    graph = project_graph(case_id)
    expanded = json.loads(graph.serialize(format="json-ld"))
    ctx = context()
    frame = {
        "@context": ctx,
        "@id": project_iri(case_id),
        "@embed": "@always",
    }
    framed = _scheme_links(jsonld.frame(expanded, frame, {"omitGraph": True}))
    # Readers get the context in full, not a link to one.
    framed["@context"] = copy.deepcopy(ctx)
    return framed
