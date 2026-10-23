-- Access for the demo (design doc: Governance with Unity Catalog). Applied with scripts/apply_grants.sh.
--
-- Free Edition note (2026-10-21): Unity Catalog grants accept only account-level identities. The groups made by
-- scripts/create_identities.sh (wb_engineers, wb_analysts, wb_auditors) are workspace-local, so Unity Catalog
-- cannot find them ("Could not find principal with name wb_engineers"). The service principal resolves, so the
-- grants below go to the agent's service principal wb_agent_sp (application id below). With a paid workspace and
-- account-level groups, the per-group grants in the design doc apply.

-- The agent's service principal reads gold only: the tables and index the agents query.
GRANT USE CATALOG ON CATALOG wb_demo TO `a8d69acf-15e5-44fa-9cf0-0406432dafb7`;
GRANT USE SCHEMA, SELECT ON SCHEMA wb_demo.gold TO `a8d69acf-15e5-44fa-9cf0-0406432dafb7`;
