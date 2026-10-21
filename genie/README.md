# Genie space: World Bank development data

The data analyst agent's text-to-SQL engine. Definition: `wb_space.json` (Genie serialized space, version 2).

- Create: `genie/create_space.sh <warehouse_id>` (prints the new `space_id`)
- Test: `python3 genie/smoke_test.py <space_id> <warehouse_id>` — 5 numeric questions, each checked against SQL on the gold table

Dev workspace space id: `01f1ccf0ce021ae2bbdb20a34b5b1c25` (created 2026-10-20; smoke test 5/5).
