# Archived configuration files

This directory holds configuration files that have been superseded by a new
source of truth. They are kept on disk for historical reference and to ease
forensic comparison; **no production code should read from here**.

## `governance_rules.json` / `governance_rules.example.json`

- **Status**: deprecated as of 2026-06-22 (per docs/document_normalize_defects.md §12).
- **Schema**: 1.x (4 classifications D1/D2/D3/D4 + 14 knowledge_types).
- **Replaced by**:
  - **Authoritative source**: DB table `governance_rules_version` (active row).
  - **On-disk mirror / proposal staging**: `config/governance_rules_v2.json`
    (schema 2.1: 11 v3.0 business classifications + 16 knowledge_types with
    classification ↔ KT mapping; tags derived per-classification via
    `tag_dimensions`, no longer a top-level array).
- **Why archived**:
  - The four `D1-D4` codes were security-level groupings, not business
    classifications. AI governance prompts emit business codes such as
    `sector_report` / `industry_policy` / `teaching_standard`, which never
    matched the old `applicable_classifications` lists, breaking knowledge
    type inference and the entire indexing path (see asset
    `4abe6b71-9b07-488d-a04f-863fee14ebe7` post-mortem in §11/§12).
  - The 14 KTs in the old file lacked `kb_id` / `rag_partition` slots
    needed for the upcoming RAGFlow KB-per-KT registration; v2.1 adds them.
- **How to seed the new content into the DB**: run once after human review
  approves `config/governance_rules_v2.json`:
  ```bash
  python scripts/seed_governance_rules_v2.py --dry-run   # preview
  python scripts/seed_governance_rules_v2.py             # actually write
  ```
- **Code change**: `nexus_app/knowledge/config_loader.py` now reads
  `config/governance_rules_v2.json`. The runtime registry
  (`nexus_app.ai_governance.rules_registry`) reads from DB.

If you really need the old file at its historical path for a one-off
script, symlink it back: `ln -s archived/governance_rules.json config/governance_rules.json`.
Do not commit such a symlink.
