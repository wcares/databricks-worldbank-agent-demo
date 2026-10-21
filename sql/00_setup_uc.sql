-- Phase 0: Unity Catalog layout (already applied to the Free Edition workspace on 2026-10-20).
CREATE CATALOG IF NOT EXISTS wb_demo;
CREATE SCHEMA IF NOT EXISTS wb_demo.bronze;  -- raw data as landed
CREATE SCHEMA IF NOT EXISTS wb_demo.silver;  -- cleaned, typed data
CREATE SCHEMA IF NOT EXISTS wb_demo.gold;    -- analysis-ready tables, vector index, agent tool functions
CREATE SCHEMA IF NOT EXISTS wb_demo.ml;      -- registered agent model, eval set, eval results
CREATE SCHEMA IF NOT EXISTS wb_demo.ops;     -- app logs, job run records, audit views
CREATE VOLUME IF NOT EXISTS wb_demo.bronze.raw_docs;  -- World Bank report PDFs + metadata JSON
