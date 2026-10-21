-- Access roles for the demo (design doc: Governance with Unity Catalog).
-- Applied by the workspace owner (scripts/apply_grants.sh). Groups and the service principal come from
-- scripts/create_identities.sh. Re-running is safe: GRANT is idempotent.
GRANT USE CATALOG ON CATALOG wb_demo TO `wb_engineers`, `wb_analysts`, `wb_auditors`, `a8d69acf-15e5-44fa-9cf0-0406432dafb7`;

-- Engineers build the pipeline: read and write bronze and silver.
GRANT USE SCHEMA, SELECT, MODIFY, CREATE TABLE ON SCHEMA wb_demo.bronze TO `wb_engineers`;
GRANT USE SCHEMA, SELECT, MODIFY, CREATE TABLE ON SCHEMA wb_demo.silver TO `wb_engineers`;
GRANT READ VOLUME, WRITE VOLUME ON VOLUME wb_demo.bronze.raw_docs TO `wb_engineers`;

-- Analysts and the agent's service principal read gold only.
GRANT USE SCHEMA, SELECT ON SCHEMA wb_demo.gold TO `wb_analysts`, `a8d69acf-15e5-44fa-9cf0-0406432dafb7`;

-- Auditors read the ops schema (audit views, request log, job runs).
GRANT USE SCHEMA, SELECT ON SCHEMA wb_demo.ops TO `wb_auditors`;
