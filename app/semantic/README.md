# Semantic export (JSON-LD)

Turns one project's data into a JSON-LD document described with the
[BIOFIN-EU ontology](https://github.com/BIOFIN-EU/ontology) (`https://w3id.org/biofineu/`),
using [R2RML](https://www.w3.org/TR/r2rml/) mapping rules. Where the ontology has no
term for something, the dashboard's extension ontology (`bfx:`) is used.

```
Postgres ──R2RML mappings──► RDF graph ──frame (context.jsonld)──► JSON-LD document
          (Morph-KGC)
```

- **Endpoint:** `GET /api/semantic/projects/{case_id}` → `application/ld+json`, for
  users who can view the project (the frontend's **Export** tab downloads it).
  Also `GET /api/semantic/ontology/ext` (the extension ontology, Turtle) and
  `GET /api/semantic/context` (the JSON-LD context).
- **IRIs:** `https://ontology.<env>.biofindashboard.eu/…` where `<env>` is the
  `SEMANTIC_ENV` setting: `dev` (default) or `prd`. Set `SEMANTIC_ENV=prd` in
  production. Files use the placeholder `{{BASE}}` for this address.

## Files

| Path | What it is | Change it to… |
|---|---|---|
| `mappings/*.r2rml.ttl` | R2RML rules, one file per area: `project` (project, NbS, sites, risk links), `finance`, `parties` (operators, intermediaries, documents), `bng`, `vocabularies` (lookup tables as SKOS concept schemes) | map a new column or table, or change which term a column maps to |
| `ontology/biofin-ext.ttl` | The extension ontology (`bfx:`): every term the mappings use that the base ontology lacks, each linked to the base ontology or a standard vocabulary | add or document an extension term; terms marked *Candidate for biofineu* could move into the base ontology |
| `concepts/concept-schemes.ttl` | Names of the concept schemes, and the BNG roles (defined in code, not a table) with the role class each corresponds to | add a scheme or a role |
| `context.jsonld` | JSON-LD context: the prefixes used in the document | add a prefix for a new vocabulary |
| `shapes/export-shapes.ttl` | SHACL shapes the export must satisfy (checked by the tests) | add a rule for a new mapping |
| `service.py` | Fills in the placeholders, runs the mappings, frames the result | change how the document is built |
| `COVERAGE.md` | Every table and column: mapped (to which term), extension, or left out and why | keep up to date with the mappings |

## Placeholders in the mapping files

- `{{BASE}}` – the base IRI (see above).
- `{{CASE_ID}}` – the exported project's id. **Every query that reads project data
  must filter on it**, so an export never reads another project. Lookup tables
  (`vocabularies.r2rml.ttl`) are read whole; the document only keeps the concepts
  the project refers to.

Formats, done in SQL so the mappings stay standard R2RML: timestamps as
`to_char(x AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')` with
`rr:datatype xsd:dateTime`; numbers cast to text (`::text`) to keep their exact
value; JSON answers read with `data->>'field'`.

## Adding a column to the export

1. Find the mapping for its table (`grep -l <table> mappings/*.ttl`) and add a
   `rr:predicateObjectMap` (select the column in the `rr:sqlQuery` first).
2. Use a term from the base ontology, or a standard vocabulary (Dublin Core,
   GeoSPARQL, SKOS, PROV, schema.org) where it fits; otherwise declare a `bfx:` term
   in `ontology/biofin-ext.ttl` with `rdfs:label`, `rdfs:comment` and, where possible,
   `rdfs:subPropertyOf`/`rdfs:subClassOf`.
3. Add a SHACL rule in `shapes/export-shapes.ttl` if it has a fixed format.
4. Update `COVERAGE.md`.
5. Run the tests (they fail if a `bfx:` term is used but not declared):

   ```
   docker exec physical-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -qc "CREATE DATABASE physical_pytest_tmp"'
   docker exec -w /usr/src/application -e POSTGRES_DB=physical_pytest_tmp physical-api python -m pytest -q tests/test_semantic_export.py
   docker exec physical-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -qc "DROP DATABASE physical_pytest_tmp"'
   ```

## Left out on purpose

Users and access rights, audit logs, drafts, workflow runs, consents; contact
details of operators and intermediaries; document storage details; the personal
answers of the BNG Site Registration step (`landowner_name`, `contact_email`,
excluded in `bng.r2rml.ttl`). See `COVERAGE.md`.

## Later

- **Choosing what to export:** the mapping files are split by area, so an export
  could include only some (e.g. `?sections=project,sites`). The frontend's Export
  tab lists downloadable files (`DOWNLOADS` in
  `src/app/(signed-in)/projects/[caseId]/export/page.tsx`): add an entry there for a
  new file.
- **Risk scores:** only linked (`biofineu:hasRiskProfile` → `data/risk-score/<id>`);
  their content lives in the risk framework's own database.
- **Morph-KGC upgrades:** `service.py` uses Morph-KGC's internal steps to parse the
  mappings once per process and share database connections (about 5x faster than
  `morph_kgc.materialize()`); check it when upgrading the pinned version.
