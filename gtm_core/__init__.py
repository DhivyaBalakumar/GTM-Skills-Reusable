"""gtm_core — shared building blocks for the GTM skills in this repo.

Modules:
  config     load the single GTM config (ICP, weights, routing)
  normalize  domains, emails, names, countries, seniority, committee roles
  dedupe     entity resolution + survivorship + lineage
  scoring    explainable fit + decaying intent scores, tiers
  routing    inbound qualification, owner assignment, SLAs
  store      SQLite central data layer (schema in sql/schema.sql)
  crm        CRM write-back adapters (dry-run, HubSpot, Salesforce)
  http       retrying, rate-limited, idempotent API client
  jobs       scheduled-job runner: locks, retries, dead-letter, alerts
  llm        Claude JSON wrapper with schema checks and offline mock
"""
__version__ = "0.1.0"
