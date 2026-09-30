# Mapping coverage

Every table of the physical database and where its columns go in the JSON-LD
export. **Base** = BIOFIN-EU ontology (`biofineu:`), **Std** = a standard vocabulary,
**Ext** = the dashboard extension (`bfx:`, `ontology/biofin-ext.ttl`), **Out** = left
out. IRIs are relative to `https://ontology.<env>.biofindashboard.eu/`.

Common to all tables: `id` becomes part of the node's IRI; `created_by`,
`updated_by`, `deleted_by` and other user ids are **Out** (personal data); deleted
rows (`deleted_at`) are not exported.

## Project and pathway data (`mappings/project.r2rml.ttl`, `finance.r2rml.ttl`, `parties.r2rml.ttl`)

| Table.column | Maps to | Kind |
|---|---|---|
| `cases` | `data/project/{id}` a `biofineu:NbSProduct` (BNG: `bfx:HabitatBank` ⊂ NbSProduct, or `bfx:Development`) | Base / Ext |
| `cases.case_type` | `bfx:pathway` → concept `concept/pathway/{code}` | Ext |
| `cases.status` | `bfx:workflowStatus` | Ext |
| `cases.created_at`, `updated_at` | `dcterms:created`, `dcterms:modified` | Std |
| `case_basic_info.name` | `dcterms:title`, `rdfs:label` | Std |
| `case_basic_info.high_level_description` | `dcterms:description` | Std |
| `case_nature_based_solutions` | `data/nbs/{id}` a `biofineu:NbS`; `biofineu:containsNbSProduct` → project, and project `biofineu:isContainedInNbS` → NbS | Base |
| `….nbs_type_id` | `bfx:hasNbSType` → `concept/nbs-type/{code}` | Ext |
| `….nbs_environment_type_id` | `bfx:hasEnvironmentType` (MAES classes; not `biofineu:hasLandCoverClassification`, which expects CORINE) | Ext |
| `….nbs_approach_type_id` | `bfx:hasApproachType` | Ext |
| `….nbs_intervention_type_id` | `bfx:hasInterventionType` | Ext |
| `….nbs_societal_challenge_type_id` | `bfx:addressesSocietalChallenge` | Ext |
| `….implementation_stage_id` | `bfx:hasImplementationStage` | Ext |
| `….nbs_description` | `dcterms:description` | Std |
| `case_locations` | `data/site/{id}` a `bfx:Site` (⊂ `geo:Feature`); project `bfx:hasSite` | Ext / Std |
| `case_locations.geometry_wkt` (or `longitude`/`latitude`) | `geo:hasGeometry` → `geo:Geometry` with `geo:asWKT` (CRS84) | Std |
| `case_locations.area_sqm` | `geo:hasMetricArea` | Std |
| `case_locations.country_id` | `bfx:country` → `concept/country/{code}` (`skos:exactMatch` EU country list); NbS `biofineu:locatedInNUTSRegion` → `nuts:code/{NUTS0}` | Ext / Base |
| `case_locations.risk_id` | NbS `biofineu:hasRiskProfile` → `data/risk-score/{risk_id}` a `biofineu:RiskScore`, `biofineu:calculatedForRegion` → the site's geometry | Base |
| `case_locations.friendly_name`, `notes`, `location_type` | `rdfs:label`, `rdfs:comment`, `bfx:locationType` | Std / Ext |
| `case_locations.area_is_manual` | – | Out (UI detail) |
| `case_financials` | `data/loan/{id}` a `fibo-loan:Loan`; project `biofineu:usesFinancialInstrument` | Base |
| `case_financials.loan_amount`, `currency` | `bfx:principalAmount` → `schema:MonetaryAmount` (`schema:value`, `schema:currency`) | Ext / Std |
| `case_financials.use_of_proceeds_id` | project `biofineu:hasFinancingPurpose` → concept (also a FIBO `Objective`) | Base |
| `case_financials.nature_positive_percentage`, `notes` | `bfx:naturePositivePercentage`, `rdfs:comment` | Ext / Std |
| `case_financing_types` | project `bfx:financingType` → concept | Ext |
| `case_funding_requirements` | `data/funding-requirement/{id}` a `bfx:FundingRequirement`; amounts as `bfx:totalFunding`, `upfrontCosts`, `maintenanceCosts`, `directFunding`, `indirectFunding` → `schema:MonetaryAmount`; `funding_notes` → `rdfs:comment` | Ext |
| `case_investment_rationales` | `bfx:naturePositiveBenefits`, `bfx:legislationCompliance`, `bfx:additionalRationale` | Ext |
| `case_identifiers` | `bfx:organicFarmerNumber`, `bfx:environmentSchemeNumber`, `bfx:subsidyReference` (⊂ `dcterms:identifier`) | Ext |
| `case_identifiers.registry_notes` | – | Out (free text, not yet mapped) |
| `operators` | `data/operator/{id}` a `commons-pty:Party` (`foaf:name`); project `biofineu:hasOperator`; role a `biofineu:OperatorRole` | Base |
| `operators.operator_specialty_id` | `bfx:operatorSpecialty` → concept | Ext |
| `operators.email`, `phone`, `notes` | – | Out (contact details) |
| `case_intermediaries` | `data/intermediary-role/{id}` a `bfx:IntermediaryRole` (⊂ `biofineu:Role`); project `biofineu:involvesRole`; `bfx:intermediaryFunction` → concept; `bfx:heldBy` → the intermediary | Ext / Base |
| `intermediaries.name` | `data/intermediary/{id}` a `commons-pty:Party`, `foaf:name` | Base |
| `intermediaries.address`, `phone`, `email`, `contact_details`, `notes` | – | Out (contact details) |
| `intermediary_function_assignments` | – | Out (which functions an intermediary offers in general, not project data) |
| `case_documents` | `data/document/{id}` a `foaf:Document`: `dcterms:title` (original file name), `dcterms:format`, `dcat:byteSize`, `bfx:stepCode`, `bfx:fieldName`, `rdfs:comment`, `dcterms:created`; project `bfx:hasSupportingDocument` | Std / Ext |
| `case_documents.stored_filename`, `upload_token`, `storage_provider`, `bucket_name`, `object_key` | – | Out (storage internals) |
| `case_consents` | – | Out (process data) |
| `case_user_access`, `case_access_audit_logs` | – | Out (users and access) |

## Biodiversity Net Gain (`mappings/bng.r2rml.ttl`)

| Table.column | Maps to | Kind |
|---|---|---|
| `bng_habitat_parcels` | `data/habitat-parcel/{id}` a `bfx:HabitatParcel` (⊂ `geo:Feature`); project `bfx:hasHabitatParcel`; `bfx:phase`, `bfx:habitatCategory`, `bfx:habitatType` / `bfx:habitatCondition` / `bfx:strategicSignificance` → concepts, `bfx:parcelSize` with `bfx:sizeUnit` (QUDT `unit:HA` / `unit:KiloM`), `bfx:biodiversityUnits`; `parcel_name` → `rdfs:label` | Ext |
| `bng_unit_allocations` | `data/allocation/{id}` a `bfx:UnitAllocation` (⊂ `prov:Entity`); development `bfx:hasUnitAllocation`, bank `bfx:suppliesUnitAllocation`; `bfx:allocationStatus`, units, `bfx:developmentProject`/`bfx:habitatBankProject` (the other project by IRI only), prices → `schema:MonetaryAmount` (GBP), `prov:generatedAtTime`, `bfx:decidedAt`/`allocatedAt`/`retiredAt`/`releasedAt` | Ext / Std |
| `bng_transactions` | `data/transaction/{id}` a `bfx:UnitTransaction` (⊂ `prov:Activity`); linked from both projects (`bfx:hasTransaction`); `bfx:transactionReference`, `bfx:fromAllocation`, units, revenue shares, `bfx:totalPrice`, `prov:endedAtTime` | Ext / Std |
| `bng_monitoring_reports` | `data/monitoring-report/{id}` a `biofineu:MonitoringReport`; bank `biofineu:producesMonitoringReport`, report `biofineu:reportsOn` bank, `biofineu:hasReportingDate` (submitted); `bfx:monitoringYear`, `dueDate`, `monitoringStatus`, `habitatsOnTrack`, `conditionSummary`, `managementCarriedOut`, `onBehalf`, `verificationNotes`, `verifiedAt`, `verifiedAsRole` | Base / Ext |
| `bng_monitoring_reports.submitted_by`, `verified_by` | – | Out (user ids) |
| `bng_remedial_actions` | `data/remedial-action/{id}` a `bfx:RemedialAction` (⊂ `biofineu:NaturePositiveActivity`); report `bfx:requiresRemedialAction`; `dcterms:description`, `bfx:dueDate`, `bfx:actionStatus`, `bfx:completionNotes`, `prov:endedAtTime` | Ext / Base |
| `bng_step_signoffs` | `data/signoff/{id}` a `bfx:StepSignoff` (⊂ `prov:Activity`); project `bfx:hasSignoff`; `bfx:stepCode`, `bfx:decision`, `bfx:signedOffAsRole` → BNG role concept, `bfx:onBehalf`, `rdfs:comment`, `prov:endedAtTime` | Ext |
| `bng_step_signoffs.user_id` | – | Out (user id) |
| `bng_step_data` (every step) | `data/step-record/{id}` a `bfx:StepRecord`, with a `bfx:StepAnswer` (`bfx:fieldName`, `rdf:value`) per plain answer | Ext |
| `bng_step_data` HMMP `monitoring_frequency` | project `biofineu:hasReportingFrequency` | Base |
| `bng_step_data` HMMP `management_period_years` | `bfx:managementPeriodYears` | Ext |
| `bng_step_data` Legal Security | `…/legal-agreement` a `bfx:ConservationCovenant` (⊂ FIBO `Contract`): `bfx:agreementType`, `dcterms:identifier`, `bfx:responsibleBody`, `dcterms:date` | Ext / Std |
| `bng_step_data` Unit Pricing prices | project `bfx:pricePerHabitatUnit` / `Hedgerow` / `Watercourse` → `schema:MonetaryAmount` (GBP) | Ext |
| `bng_step_data` Site Registration `landowner_name`, `contact_email` | – | Out (personal) |
| `bng_step_data` answers that are lists or files (e.g. `bng_documents`) | – | Out (not plain values) |
| `bng_case_roles` | – | Out (which user holds which role; the roles appear on sign-offs) |

## Code lists (`mappings/vocabularies.r2rml.ttl`, `concepts/concept-schemes.ttl`)

Each becomes a `skos:ConceptScheme` `concept/{scheme}` with a `skos:Concept` per row
(`skos:prefLabel` = name, `skos:definition` = description, `skos:notation` = code):
`nbs_types`, `nbs_environment_types`, `nbs_approach_types`,
`nbs_intervention_types` (+ `bfx:interventionCategory`), `nbs_societal_challenge_types`,
`implementation_stages`, `financing_types`, `use_of_proceeds`, `operator_specialties`,
`intermediary_functions` (+ `bfx:functionCategory`), `bng_habitat_types`
(+ category, distinctiveness), `bng_conditions` and `bng_strategic_significance`
(+ `bfx:multiplier`), `currencies` (`skos:exactMatch` EU currency list), `countries`
(`skos:exactMatch` EU country list), `workflow.workflow_definitions` (pathways). BNG
roles come from `concepts/concept-schemes.ttl`, each with `bfx:roleClass`
(`biofineu:LandOwnerRole`, `biofineu:FunderRole`, `biofineu:LocalGovernmentRole`,
`bfx:DeveloperRole`, `bfx:EcologistRole`).

## Not exported (whole tables)

`workflow.case_step_drafts` (unsaved drafts), `workflow.case_workflow_runs`
(engine state; the project's status is exported), `case_data.alembic_version`.
