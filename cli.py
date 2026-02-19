#!/usr/bin/env python3
"""
cli.py — Click CLI for running schema intelligence tools without Claude.

Usage:
    python cli.py search care --custom-only
    python cli.py describe Account
    python cli.py relationships Account
    python cli.py er Account Contact --depth 2 --format plantuml
    python cli.py hierarchy Account
    python cli.py diff ./cache-v1 ./cache-v2
    python cli.py meta
"""
from __future__ import annotations

import json
import os
import sys

import click

from src.core import diff, er_diagram, graph
from src.data import schema_cache

CACHE_ROOT = os.environ.get("SF_SCHEMA_CACHE", "./schema-cache")


@click.group()
@click.option("--cache-dir", default=None, envvar="SF_SCHEMA_CACHE",
              help="Path to schema cache directory.")
@click.option("--org", "org_alias", default=None,
              help="Org alias (resolves to cache subdirectory via _orgs.json).")
@click.pass_context
def cli(ctx: click.Context, cache_dir: str | None, org_alias: str | None) -> None:
    """Salesforce Schema Intelligence CLI."""
    ctx.ensure_object(dict)
    if org_alias:
        ctx.obj["cache_dir"] = str(schema_cache.resolve_org_cache_dir(CACHE_ROOT, org_alias))
    elif cache_dir:
        ctx.obj["cache_dir"] = cache_dir
    else:
        ctx.obj["cache_dir"] = CACHE_ROOT


@cli.command()
@click.argument("keyword")
@click.option("--custom-only", is_flag=True, help="Show only custom objects.")
@click.pass_context
def search(ctx: click.Context, keyword: str, custom_only: bool) -> None:
    """Search for objects by keyword in name or label."""
    index = schema_cache.load_index(ctx.obj["cache_dir"])
    kw = keyword.lower()
    matches = [
        o for o in index
        if (kw in o["name"].lower() or kw in o["label"].lower())
        and (not custom_only or o["custom"])
    ]
    if not matches:
        click.echo(f"No objects matching '{keyword}'.")
        return
    click.echo(f"Found {len(matches)} object(s):")
    for o in matches:
        kind = "custom" if o["custom"] else "standard"
        click.echo(f"  {o['name']}  —  {o['label']}  ({kind}, {o['field_count']} fields)")


@cli.command()
@click.argument("object_name")
@click.pass_context
def describe(ctx: click.Context, object_name: str) -> None:
    """Show full schema for a Salesforce object."""
    obj = schema_cache.load_object(ctx.obj["cache_dir"], object_name)
    if not obj:
        click.echo(f"Object '{object_name}' not found.", err=True)
        raise SystemExit(1)
    click.echo(f"Object: {obj['name']} ({obj['label']})")
    click.echo(f"Custom: {obj['custom']}")
    click.echo(f"\nFields ({len(obj['fields'])}):")
    for f in obj["fields"]:
        ref = f" -> {', '.join(f['reference_to'])}" if f.get("reference_to") else ""
        req = " [REQUIRED]" if f.get("required") else ""
        click.echo(f"  {f['name']} ({f['type']}){ref}{req}")
    if obj.get("child_relationships"):
        click.echo(f"\nChild Relationships ({len(obj['child_relationships'])}):")
        for r in obj["child_relationships"]:
            click.echo(f"  <- {r['child_sobject']}.{r['field']} (rel: {r['relationship_name']})")


@cli.command()
@click.argument("object_name")
@click.pass_context
def relationships(ctx: click.Context, object_name: str) -> None:
    """Show relationships for a Salesforce object."""
    obj = schema_cache.load_object(ctx.obj["cache_dir"], object_name)
    if not obj:
        click.echo(f"Object '{object_name}' not found.", err=True)
        raise SystemExit(1)
    rel_fields = [
        f for f in obj["fields"]
        if f["type"] in ("reference", "masterdetail") and f.get("reference_to")
    ]
    click.echo(f"Relationships for {obj['name']}:\n")
    click.echo("Outbound:")
    for f in rel_fields:
        click.echo(f"  {f['name']} ({f['type']}) -> {', '.join(f['reference_to'])}")
    if not rel_fields:
        click.echo("  None")
    click.echo("\nInbound:")
    for r in obj.get("child_relationships", []):
        click.echo(f"  {r['child_sobject']}.{r['field']} (rel: {r['relationship_name']})")
    if not obj.get("child_relationships"):
        click.echo("  None")


@cli.command()
@click.argument("root_objects", nargs=-1, required=True)
@click.option("--depth", default=1, type=int, help="Relationship traversal depth (0-3).")
@click.option("--direction", default="both", type=click.Choice(["both", "outbound", "inbound"]))
@click.option("--include-fields/--no-fields", default=True)
@click.option("--field-filter", default="relationships",
              type=click.Choice(["all", "required", "relationships"]))
@click.option("--format", "fmt", default="mermaid", type=click.Choice(["mermaid", "plantuml"]))
@click.pass_context
def er(
    ctx: click.Context,
    root_objects: tuple[str, ...],
    depth: int,
    direction: str,
    include_fields: bool,
    field_filter: str,
    fmt: str,
) -> None:
    """Generate an ER diagram from the schema cache."""
    snapshot = schema_cache.load_snapshot(ctx.obj["cache_dir"])
    g = graph.build_graph(snapshot)
    objects_map, edges = graph.collect_subgraph(g, list(root_objects), depth, direction)
    if not objects_map:
        click.echo("No objects found to diagram.", err=True)
        raise SystemExit(1)
    diagram = er_diagram.generate_er_diagram(
        objects_map, edges,
        include_fields=include_fields,
        field_filter=field_filter,
        max_fields=20,
        format=fmt,
    )
    click.echo(diagram)


@cli.command()
@click.argument("object_name")
@click.option("--max-levels", default=3, type=int, help="Hierarchy depth (1-6).")
@click.option("--format", "fmt", default="mermaid", type=click.Choice(["mermaid", "plantuml"]))
@click.pass_context
def hierarchy(ctx: click.Context, object_name: str, max_levels: int, fmt: str) -> None:
    """Generate a hierarchy diagram for a self-referencing object."""
    snapshot = schema_cache.load_snapshot(ctx.obj["cache_dir"])
    result = er_diagram.generate_hierarchy_diagram(object_name, snapshot, max_levels, fmt)
    click.echo(result)


@cli.command(name="diff")
@click.argument("cache_dir_a")
@click.argument("cache_dir_b")
@click.option("--json-output", is_flag=True, help="Output as JSON instead of text.")
def diff_cmd(cache_dir_a: str, cache_dir_b: str, json_output: bool) -> None:
    """Compare two schema snapshots."""
    snap_a = schema_cache.load_snapshot(cache_dir_a)
    snap_b = schema_cache.load_snapshot(cache_dir_b)
    result = diff.compare_snapshots(snap_a, snap_b)
    if json_output:
        click.echo(json.dumps(result.as_dict(), indent=2))
    else:
        click.echo(result.as_text_report())


@cli.command()
@click.pass_context
def meta(ctx: click.Context) -> None:
    """Show schema cache metadata."""
    m = schema_cache.load_meta(ctx.obj["cache_dir"])
    if not m:
        click.echo("No schema cache found. Run sf_schema_sync.py first.")
        return
    click.echo(json.dumps(m, indent=2))


@cli.command(name="list")
@click.option("--custom-only", is_flag=True, help="Show only custom objects.")
@click.pass_context
def list_objects(ctx: click.Context, custom_only: bool) -> None:
    """List all objects in the schema cache."""
    index = schema_cache.load_index(ctx.obj["cache_dir"])
    objs = [o for o in index if not custom_only or o["custom"]]
    click.echo(f"{len(objs)} objects:")
    for o in objs:
        click.echo(f"  {o['name']} ({o['label']}) — {o['field_count']} fields")


@cli.command()
def orgs() -> None:
    """List all synced orgs."""
    org_map = schema_cache.load_orgs(CACHE_ROOT)
    if not org_map:
        meta = schema_cache.load_meta(CACHE_ROOT)
        if meta:
            click.echo(f"Single org (legacy): {meta.get('instance_url', 'unknown')}")
        else:
            click.echo("No orgs synced. Run: python scripts/sf_schema_sync.py --org <alias>")
        return
    click.echo(f"{len(org_map)} org(s):")
    for alias, info in sorted(org_map.items()):
        click.echo(f"  {alias}: {info['instance_url']} ({info.get('username', '')})")


if __name__ == "__main__":
    cli()
