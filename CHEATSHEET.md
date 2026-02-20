# Salesforce Schema Intelligence — Cheatsheet

Quick reference for all MCP tools, CLI commands, and common workflows.

---

## Quick Start

```bash
# 1. Authenticate with Salesforce CLI
sf org login web --alias myorg --instance-url https://your-domain.my.salesforce.com

# 2. Sync schema to local cache
python scripts/sf_schema_sync.py --org myorg

# 3. Verify
python cli.py orgs
python cli.py --org myorg list
```

### MCP Server Setup

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "salesforce-schema": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "cwd": "/path/to/sf-schema-intelligence",
      "env": { "SF_SCHEMA_CACHE": "./schema-cache" }
    }
  }
}
```

**Cursor** (`~/.cursor/mcp.json` for global, `.cursor/mcp.json` for project):
```json
{
  "mcpServers": {
    "salesforce-schema": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "cwd": "/path/to/sf-schema-intelligence",
      "env": { "SF_SCHEMA_CACHE": "./schema-cache" }
    }
  }
}
```

**Claude Code**:
```bash
claude mcp add salesforce-schema -- python -m src.mcp.server
```

---

## MCP Tools Reference

### Org Management

| Tool | Parameters | Description |
|------|-----------|-------------|
| `list_orgs` | — | Show all synced orgs, mark which is active |
| `switch_org` | `org` (str) | Switch active org for all subsequent queries |
| `refresh_object` | `object_name` (str) | Re-fetch a single object's schema from Salesforce |

```
> list_orgs
Synced orgs (2):
  prod: https://mycompany.my.salesforce.com (ACTIVE)
  sandbox: https://mycompany--uat.sandbox.my.salesforce.com

> switch_org("sandbox")
Switched to 'sandbox' (https://mycompany--uat.sandbox.my.salesforce.com). Last synced: 2026-02-20T12:00:00

> refresh_object("Account")
Refreshed 'Account' from sandbox. 68 fields, 42 child relationships.
```

### Schema Exploration

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_object_schema` | `object_name` (str), `key_fields_only` (bool, default=False) | Full or key-only field definitions |
| `search_objects` | `keyword` (str), `custom_only` (bool, default=False) | Find objects by name or label |
| `list_all_objects` | `custom_only` (bool, default=False) | List all cached objects |
| `get_object_relationships` | `object_name` (str) | Outbound lookups + inbound child relationships |

```
> get_object_schema("Account")
Object: Account (Account)
Custom: False
Fields (68):
  Id (id)
  Name (string) [REQUIRED]
  ParentId (reference) -> Account
  ...

> get_object_schema("Account", key_fields_only=True)
Object: Account (Account)
Key Fields (15 of 68 total):
  Id (id)
  OwnerId (reference) -> User [REQUIRED]
  ParentId (reference) -> Account
  ...
  ... 53 more fields omitted. Use key_fields_only=False for full schema.

> search_objects("provider")
Found 5 object(s):
  HealthcareProvider — Healthcare Provider (12 fields)
  HealthcareProviderNpi — Healthcare Provider NPI (8 fields)
  ...

> search_objects("care", custom_only=True)
Found 3 object(s):
  HealthCloudGA__CarePlan__c — Care Plan (45 fields)
  ...
```

### Diagrams

| Tool | Parameters | Description |
|------|-----------|-------------|
| `generate_er_diagram_tool` | `root_objects` (list), `depth` (int=1), `direction` (str="both"), `include_fields` (bool=True), `field_filter` (str="relationships"), `format` (str="mermaid") | ER diagram |
| `generate_hierarchy_diagram_tool` | `object_name` (str), `max_levels` (int=3), `format` (str="mermaid") | Self-referencing hierarchy diagram |

```
> generate_er_diagram_tool(["Account", "Contact"], depth=2)
Objects: 8 | Edges: 12
erDiagram
    Account { ... }
    Contact { ... }
    ...

> generate_er_diagram_tool(["WorkOrder"], depth=1, direction="outbound", format="plantuml")

> generate_hierarchy_diagram_tool("Account", max_levels=4)
```

**Diagram parameters explained:**

| Parameter | Values | Use When |
|-----------|--------|----------|
| `depth` | 0-3 | 0 = just the object, 1 = immediate neighbors, 2+ = wider graph |
| `direction` | `both`, `outbound`, `inbound` | `outbound` = what this object points to, `inbound` = what points to it |
| `field_filter` | `relationships`, `required`, `all` | `relationships` = FK fields only (cleanest), `all` = every field (verbose) |
| `format` | `mermaid`, `plantuml` | Mermaid for GitHub/Claude/Notion, PlantUML for draw.io/IntelliJ |

### Schema Comparison

| Tool | Parameters | Description |
|------|-----------|-------------|
| `compare_schemas` | `cache_dir_a` (str), `cache_dir_b` (str) | Diff two snapshots — accepts org aliases or paths |
| `get_schema_meta` | `cache_dir` (str, optional) | Cache metadata (last sync time, object count) |

```
> compare_schemas("sandbox", "prod")
Schema Diff Report
  Added objects: CustomObj__c
  Removed objects: (none)
  Modified objects:
    Account: 2 field changes (1 BREAKING)
      - REMOVED: Legacy_Field__c (BREAKING)
      - ADDED: New_Field__c (non-breaking)

> get_schema_meta()
{
  "synced_at": "2026-02-20T12:00:00+00:00",
  "instance_url": "https://mycompany.my.salesforce.com",
  "objects_synced": 64,
  "objects_failed": 0,
  "api_version": "v60.0"
}
```

---

## Common Workflows

### Set Up a New Org

```bash
# Step 1: Authenticate (opens browser)
sf org login web --alias prod --instance-url https://mycompany.my.salesforce.com

# Step 2: Verify connection
sf org display --target-org prod

# Step 3: Sync all objects (takes 2-5 min depending on org size)
python scripts/sf_schema_sync.py --org prod

# Step 4: Verify in MCP
> list_orgs
> get_schema_meta("prod")
```

### Switch Between Sandboxes

```
> list_orgs
Synced orgs (3):
  prod: https://mycompany.my.salesforce.com (ACTIVE)
  uat: https://mycompany--uat.sandbox.my.salesforce.com
  dev: https://mycompany--dev.sandbox.my.salesforce.com

> switch_org("uat")
Switched to 'uat'. Last synced: 2026-02-19T08:30:00

> get_object_schema("Account")
# Now returns Account from UAT sandbox
```

### Full Sync (All Objects)

```bash
# Sync everything — discovers all queryable objects automatically
python scripts/sf_schema_sync.py --org prod

# Output:
#   Fetching SObject list...
#   Found 68 queryable objects.
#   [1/68] Account... OK
#   [2/68] Contact... OK
#   ...
#   Done. Synced: 64, Failed: 4
```

### Incremental Refresh (Single Object)

Use when you've just added or modified fields in Salesforce:

```
# Via MCP tool (no terminal needed)
> refresh_object("Account")
Refreshed 'Account' from prod. 68 fields, 42 child relationships.
```

Or sync specific objects from the terminal:

```bash
# Sync only Account and Contact
python scripts/sf_schema_sync.py --org prod --objects Account --objects Contact
```

### Compare Sandbox vs Production

```
# Via MCP (use org aliases)
> compare_schemas("sandbox", "prod")

# Via CLI (use directory paths)
python cli.py diff ./schema-cache/sandbox ./schema-cache/prod

# JSON output for programmatic use
python cli.py diff ./schema-cache/sandbox ./schema-cache/prod --json-output
```

### Generate ER Diagram for a Domain

```
# Start from key objects, expand 2 levels
> generate_er_diagram_tool(["WorkOrder", "ServiceAppointment"], depth=2)

# Outbound only (what these objects reference)
> generate_er_diagram_tool(["Account"], depth=1, direction="outbound")

# Show all fields (verbose)
> generate_er_diagram_tool(["Contact"], depth=1, field_filter="all")

# PlantUML format for draw.io
> generate_er_diagram_tool(["Case"], depth=1, format="plantuml")
```

---

## CLI Commands

All commands support `--org <alias>` to target a specific org.

```bash
# List all synced orgs
python cli.py orgs

# List all objects in an org
python cli.py --org prod list
python cli.py --org prod list --custom-only

# Search objects by keyword
python cli.py --org prod search provider
python cli.py --org prod search care --custom-only

# Describe a single object (full schema)
python cli.py --org prod describe Account

# Show relationships
python cli.py --org prod relationships Account

# Generate ER diagram
python cli.py --org prod er Account Contact --depth 2 --format mermaid
python cli.py --org prod er WorkOrder --depth 1 --direction outbound

# Generate hierarchy diagram
python cli.py --org prod hierarchy Account --max-levels 4

# Compare two org schemas
python cli.py diff ./schema-cache/sandbox ./schema-cache/prod
python cli.py diff ./schema-cache/sandbox ./schema-cache/prod --json-output

# View cache metadata
python cli.py --org prod meta
```

---

## Sync Script

```bash
python scripts/sf_schema_sync.py [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--org <alias>` | Salesforce CLI org alias (recommended). Gets credentials via `sf org display`. |
| `--cache-dir <path>` | Explicit cache directory. Auto-resolved from `--org` if omitted. |
| `--objects <name>` | Sync specific objects only (repeatable). Omit to sync all queryable objects. |

```bash
# Full sync using org alias (recommended)
python scripts/sf_schema_sync.py --org prod

# Sync specific objects only (fast)
python scripts/sf_schema_sync.py --org prod --objects Account --objects Contact --objects Opportunity

# Legacy mode using env vars (no --org)
SF_INSTANCE_URL=https://... SF_ACCESS_TOKEN=tok... python scripts/sf_schema_sync.py

# Daily cron job
0 6 * * * cd /path/to/sf-schema-intelligence && python scripts/sf_schema_sync.py --org prod
```

---

## Environment Variables

| Variable | Default | Used By |
|----------|---------|---------|
| `SF_SCHEMA_CACHE` | `./schema-cache` | All components — root directory for cached schemas |
| `SF_INSTANCE_URL` | — | Sync script only (legacy mode, without `--org`) |
| `SF_ACCESS_TOKEN` | — | Sync script only (legacy mode, without `--org`) |

---

## Cache Directory Structure

```
schema-cache/
  _orgs.json                 # org registry (alias -> cache dir, instance URL)
  prod/                      # one subdirectory per org
    Account.json             # one file per SObject
    Contact.json
    Opportunity.json
    _index.json              # summary: name, label, custom, field_count
    _meta.json               # sync timestamp, instance URL, counts
  sandbox/
    Account.json
    _index.json
    _meta.json
```
