# Salesforce Schema Intelligence

Deterministic, org-specific Salesforce schema intelligence for LLMs — via MCP.

## The Problem This Solves

### LLMs Don't Know Your Org

Large language models like Claude, GPT-5x, and Gemini are trained on data up to a cutoff date. For Salesforce developers and architects, this creates three compounding problems:

**1. Salesforce releases 3 times a year.**
Salesforce ships major releases in Spring, Summer, and Winter — each introducing new standard objects, deprecated fields, changed relationships, and  Industry cloud Objects  such as new Health Cloud or Financial Services Cloud objects. A model trained in early 2024 knows nothing about Winter 2025 changes. Ask it to write Apex against a new object and it will confidently produce code that does not compile.

**2. Every org is different.**
No two Salesforce orgs share the same schema. A Healthcare org has hundreds of custom objects, client-specific fields on standard objects, industry-specific junction objects, and namespace prefixes from installed managed packages. A Financial Services org has its own custom policy, claim, and account hierarchies. Claude knows the generic product. It does not know YOUR org.

**3. Hallucination compounds with complexity.**
When an LLM does not know a field name, it guesses plausibly. `ProviderStatus__c` becomes `Status__c`. `InsurancePolicy__c` becomes `Policy__c`. In a SOQL query this is a compile error. In an Apex trigger deployed to production, it is an incident.

### The Solution

sf-schema-intelligence exports your org's real schema to a local cache and exposes it to any LLM via the Model Context Protocol (MCP). The LLM calls your schema tools before answering — getting accurate, org-specific field names, types, and relationships before writing a single line of code.

**Without sf-schema-intelligence:**

```
You: "Write a SOQL query for active Healthcare Providers"
LLM: SELECT Id, Status__c FROM Provider__c WHERE Status__c = 'Active'
           ^ wrong field       ^ wrong object name   ^ wrong value
```

**With sf-schema-intelligence:**

```
You: "Write a SOQL query for active Healthcare Providers"
LLM: [calls get_object_schema("HealthcareProvider__c")]
     SELECT Id, ProviderStatus__c, ContractStartDate__c, PrimaryAccount__c
     FROM HealthcareProvider__c
     WHERE ProviderStatus__c = 'In Network'
     ^ exact field from your org              ^ exact picklist value
```

## Why MCP

The Model Context Protocol (MCP), open-sourced by Anthropic in 2024 and now governed by the Linux Foundation with backing from OpenAI, Google, and Microsoft, is the universal standard for connecting LLMs to external tools and data. One MCP server works across Claude, GPT-5x, Gemini, Cursor, and any other MCP-compatible client. You build the schema intelligence once. Every AI tool your team uses benefits from it.

## Architecture

```
+-----------------------------------------------------+
|  MCP Clients                                        |
|  Claude Desktop . Claude Code . Cursor . OpenAI     |
+--------------------+--------------------------------+
                     |  MCP Protocol (stdio / HTTP)
+--------------------v--------------------------------+
|  src/mcp/server.py  (FastMCP)                       |
|  Thin @mcp.tool wrappers -- no business logic       |
+--------------------+--------------------------------+
                     |  Python imports
+--------------------v--------------------------------+
|  src/core/                                          |
|  diff.py . graph.py . er_diagram.py                 |
|  Pure Python -- no MCP, no ML, fully testable       |
+--------------------+--------------------------------+
                     |  Python imports
+--------------------v--------------------------------+
|  src/data/schema_cache.py                           |
|  Load . save . index schema snapshots               |
+--------------------+--------------------------------+
                     |  JSON files
+--------------------v--------------------------------+
|  schema-cache/                                      |
|  _orgs.json (org registry)                          |
|  sfsdemo/  Account.json . _index.json . _meta.json  |
|  prod/     Account.json . _index.json . _meta.json  |
+-----------------------------------------------------+
```

**Dependency rule:** `data ← core ← mcp`. Never reversed. Core modules never import from MCP. This keeps business logic independently testable without running an MCP server.

### File Structure

```
sf-schema-intelligence/
|
|-- src/
|   |-- data/
|   |   +-- schema_cache.py      # Load, save, index snapshots (no MCP, no ML)
|   |
|   |-- core/
|   |   |-- graph.py             # NetworkX relationship graph (no MCP, no ML)
|   |   |-- diff.py              # Deterministic schema diff (no MCP, no ML)
|   |   +-- er_diagram.py        # Mermaid + PlantUML renderers (no MCP, no ML)
|   |
|   +-- mcp/
|       +-- server.py            # FastMCP server (thin wrappers, <=10 lines each)
|
|-- scripts/
|   +-- sf_schema_sync.py        # CLI sync from Salesforce REST API
|
|-- cli.py                       # Click CLI for local use without Claude
|-- tests/
|   |-- conftest.py              # Shared pytest fixtures (snapshot_v1, snapshot_v2)
|   |-- fixtures/
|   |   |-- snapshot_v1/         # 6 objects (Account, Contact, CarePlan, etc.)
|   |   +-- snapshot_v2/         # 7 objects (v1 + CareMetric, with field diffs)
|   |-- test_diff.py
|   |-- test_graph.py
|   |-- test_er_diagram.py
|   +-- test_multi_org.py
+-- pyproject.toml
```

## Prerequisites

- Python 3.11+
- A Salesforce org with API access
- Salesforce CLI (`sf`) for authentication — install from [developer.salesforce.com/tools/salesforcecli](https://developer.salesforce.com/tools/salesforcecli)

## Quick Start

### 1. Install

```bash
git clone https://github.com/yourname/sf-schema-intelligence
cd sf-schema-intelligence
pip install -e ".[dev]"
```

### 2. Authenticate with Salesforce

```bash
# Log in via browser (replace alias and URL with your org)
sf org login web --alias myorg --instance-url https://your-domain.my.salesforce.com

# Verify connection
sf org display --target-org myorg
```

No `.env` file needed when using `--org` — credentials are pulled from the Salesforce CLI automatically.

### 3. Sync Schema

```bash
# Sync specific objects using org alias (recommended)
python scripts/sf_schema_sync.py --org myorg \
  --objects Account --objects Contact --objects Opportunity \
  --objects Case --objects Lead --objects Campaign

# Sync all queryable objects (can be slow for large orgs — 4000+ objects)
python scripts/sf_schema_sync.py --org myorg
```

This creates `schema-cache/myorg/` with one JSON file per object, plus `_index.json` and `_meta.json`. The org is automatically registered in `schema-cache/_orgs.json`.

> **Tip:** Start with a targeted sync of the objects you care about. A full org sync can take a long time on orgs with many managed packages.

### 4. Verify

```bash
# List synced orgs
python cli.py orgs

# List synced objects for an org
python cli.py --org myorg list

# Describe an object
python cli.py --org myorg describe Account

# Generate an ER diagram
python cli.py --org myorg er Account --depth 1 --format mermaid
```

### 5. Run Tests

```bash
python -m pytest tests/ -v
```

70 tests covering the graph builder, diff engine, ER diagram renderers, and multi-org support.

## CLI Reference

All commands accept `--org <alias>` to target a specific org, or `--cache-dir <path>` for a raw directory.

```bash
# List synced orgs
python cli.py orgs

# Search for objects by keyword
python cli.py --org myorg search care --custom-only

# Full schema for an object
python cli.py --org myorg describe Account

# Show relationships for an object
python cli.py --org myorg relationships Account

# Generate ER diagram (Mermaid or PlantUML)
python cli.py --org myorg er Account Contact --depth 2 --format mermaid

# Generate hierarchy diagram for self-referencing objects
python cli.py --org myorg hierarchy Account --max-levels 3

# Compare two orgs' schemas
python cli.py diff ./schema-cache/sandbox ./schema-cache/prod --json-output

# List all cached objects
python cli.py --org myorg list --custom-only

# Show cache metadata (last sync, org info)
python cli.py --org myorg meta
```

## Connecting to LLM Clients

### Claude Code

```bash
claude mcp add salesforce-schema -- python -m src.mcp.server
```

Run this from the project directory. The server will appear in Claude Code's MCP tools automatically.

### Cursor

Add to `~/.cursor/mcp.json` for global access (all projects), or `.cursor/mcp.json` in a specific project:

```json
{
  "mcpServers": {
    "salesforce-schema": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "cwd": "/path/to/sf-schema-intelligence",
      "env": {
        "SF_SCHEMA_CACHE": "./schema-cache"
      }
    }
  }
}
```

Reload the Cursor window (`Cmd+Shift+P` → "Reload Window") after adding.

Add `.cursorrules` to your project root:

```
Always use the salesforce-schema MCP tools before writing Apex, SOQL, or generating ER diagrams.
Never assume field API names.
```

### Claude Desktop

Add to `claude_desktop_config.json` (found at `~/Library/Application Support/Claude/`):

```json
{
  "mcpServers": {
    "salesforce-schema": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "cwd": "/path/to/sf-schema-intelligence",
      "env": {
        "SF_SCHEMA_CACHE": "./schema-cache"
      }
    }
  }
}
```

Restart Claude Desktop. You will see "salesforce-schema" in the tools panel with 10 available tools.

### OpenAI

```python
import asyncio
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

async def main():
    sf_schema = MCPServerStdio(params={
        "command": "python3",
        "args": ["/path/to/src/mcp/server.py"],
        "env": {"SF_SCHEMA_CACHE": "/path/to/schema-cache"}
    })
    agent = Agent(
        name="Salesforce Architect",
        model="gpt-4o",
        instructions="Always call get_object_schema before writing Apex or SOQL.",
        mcp_servers=[sf_schema]
    )
    async with sf_schema:
        result = await Runner.run(
            agent,
            "Write Apex to update InsurancePolicy__c status when a Claim is approved"
        )
        print(result.final_output)

asyncio.run(main())
```

### Gemini

```python
import asyncio
from fastmcp import Client
from google import genai
from google.genai import types

async def ask(question: str) -> str:
    async with Client("/path/to/src/mcp/server.py") as mcp_client:
        response = await genai.Client().aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=question,
            config=types.GenerateContentConfig(tools=[mcp_client.session])
        )
        return response.text

asyncio.run(ask("Generate ER diagram for the insurance policy domain"))
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `list_orgs` | List all synced orgs and show which is currently active |
| `switch_org` | Switch the active org for all subsequent queries |
| `get_object_schema` | Full field definitions and relationships for an object |
| `search_objects` | Search by keyword in API name or label |
| `list_all_objects` | Summary list of all cached objects (filterable to custom only) |
| `get_object_relationships` | Lookup, master-detail, and child relationships |
| `generate_er_diagram_tool` | Deterministic Mermaid or PlantUML ER diagram with depth/direction controls |
| `generate_hierarchy_diagram_tool` | Hierarchy diagram for self-referencing objects (e.g. Account → ParentId) |
| `compare_schemas` | Structured diff between two snapshots or orgs with severity classification |
| `get_schema_meta` | Cache metadata (last sync time, org info, object count) |

## Use Case Examples

### Accurate Apex Generation (Healthcare)

**Prompt:** "Write an Apex trigger on HealthcareProvider__c that sets status to Inactive when their insurance policy expires"

**Tool calls:** `get_object_schema("HealthcareProvider__c")`, `get_object_schema("InsurancePolicy__c")`, `get_object_relationships("HealthcareProvider__c")`

**Result:** Apex with exact field names, correct SOQL relationship traversal, accurate picklist values — compiles on first attempt. No guessed field names.

### Client-Specific ER Diagrams

**Prompt:** "Generate an ER diagram for our provider network domain, 2 levels deep"

**Tool calls:** `search_objects("provider")`, `generate_er_diagram_tool(["HealthcareProvider__c", "ProviderLocation__c"], depth=2)`

**Result:** Mermaid diagram with real org objects, client custom fields included, renders in Lucid / Mermaid.live / GitHub. Not a generic diagram from training data.

### Safe Sandbox-to-Production Migration

**Prompt:** "Compare our sandbox schema to production and flag breaking changes"

**Tool calls:** `compare_schemas("sandbox", "prod")` (accepts org aliases or directory paths)

```
BREAKING (2):
  HealthcareProvider__c.ProviderStatus__c  TYPE CHANGED  text -> picklist
  InsurancePolicy__c.PolicyNumber__c       FIELD REMOVED

NON-BREAKING (14):
  Claim__c.AdjudicationNotes__c  FIELD ADDED
  ... 13 more

INFO (6): label changes, description updates
```

### Hierarchy Visualization

**Prompt:** "Show me the Account hierarchy in our org"

**Tool calls:** `generate_hierarchy_diagram_tool("Account", max_levels=3)`

**Result:** Flowchart showing self-referencing Account → Account via ParentId. Renders in draw.io and Lucidchart for client presentations.

## Diagram Rendering

| Tool | Support | How to Use |
|------|---------|------------|
| Claude Desktop / Code | Native | Renders Mermaid inline automatically |
| GitHub Markdown | Native | Paste in ` ```mermaid ` block in any .md file |
| Notion | Native | Insert code block, select Mermaid language |
| draw.io | Full | Arrange > Insert > Mermaid — converts to editable shapes |
| Lucidchart | Full | Import > Mermaid diagram |
| mermaid.live | Full | Paste and share URL — good for client presentations |
| Confluence | Via draw.io | draw.io Confluence app > Insert > Mermaid |
| PlantUML | plantuml.com | Paste `@startuml`/`@enduml` block |

## Multi-Org Support

Sync multiple orgs and switch between them without restarting the MCP server.

### Syncing Multiple Orgs

```bash
# Authenticate and sync each org
sf org login web --alias prod
python scripts/sf_schema_sync.py --org prod

sf org login web --alias sandbox
python scripts/sf_schema_sync.py --org sandbox --objects Account --objects Contact
```

This creates:

```
schema-cache/
  _orgs.json          # registry: {prod: {...}, sandbox: {...}}
  prod/               # full schema cache
  sandbox/            # targeted schema cache
```

### Switching Orgs in MCP

From Claude, Cursor, or any MCP client:

```
> list_orgs
Synced orgs (2):
  prod: https://mycompany.my.salesforce.com (ACTIVE)
  sandbox: https://mycompany--uat.sandbox.my.salesforce.com

> switch_org("sandbox")
Switched to 'sandbox'. Last synced: 2026-02-19T06:00:04+00:00

> describe Account    # now returns sandbox Account schema
```

### Switching Orgs in CLI

```bash
python cli.py --org prod describe Account
python cli.py --org sandbox describe Account
```

### Comparing Orgs

```bash
# Via MCP
compare_schemas("sandbox", "prod")

# Via CLI
python cli.py diff ./schema-cache/sandbox ./schema-cache/prod
```

### Daily Schema Refresh

```bash
crontab -e
# Add one line per org:
0 7 * * * cd /path/to/sf-schema-intelligence && python scripts/sf_schema_sync.py --org prod >> ~/logs/sf-schema.log 2>&1
0 7 * * * cd /path/to/sf-schema-intelligence && python scripts/sf_schema_sync.py --org sandbox >> ~/logs/sf-schema.log 2>&1
```

### Legacy Single-Org Mode

If you don't use `--org`, the sync script reads credentials from a `.env` file and writes directly to `schema-cache/` (no subdirectories). This is fully backward compatible — existing setups continue to work unchanged.

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | Done | Deterministic diff, ER diagrams, MCP tooling |
| 2 | Planned | Domain auto-discovery via Louvain graph clustering |
| 3 | Planned | Embedding-based rename detection (local, no API) |

**Phase 2 — Domain Auto-Discovery:** Uses NetworkX + Louvain community detection to automatically group objects into business domains (Provider Network, Policy Management, Claims etc.) without any prior configuration. Useful on day one of a new engagement.

**Phase 3 — Embedding-Based Rename Detection:** Uses sentence-transformers (runs locally, no API cost) to detect when objects or fields were renamed between versions — rather than incorrectly reporting them as a delete + add.

