"""Tests for multi-org support — registry, resolution, and MCP state."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.schema_cache import (
    load_orgs,
    resolve_org_cache_dir,
    save_orgs,
    load_meta,
    save_meta,
    save_object,
    build_index,
)


# ── Registry CRUD ────────────────────────────────────────────────────────────

class TestOrgRegistry:
    """load_orgs / save_orgs round-trip."""

    def test_load_empty_returns_empty_dict(self, tmp_path):
        assert load_orgs(tmp_path) == {}

    def test_save_and_load_round_trip(self, tmp_path):
        orgs = {
            "sfsdemo": {
                "cache_dir": str(tmp_path / "sfsdemo"),
                "instance_url": "https://example.my.salesforce.com",
                "username": "user@example.com",
                "alias": "sfsdemo",
            },
            "prod": {
                "cache_dir": str(tmp_path / "prod"),
                "instance_url": "https://prod.my.salesforce.com",
                "username": "admin@prod.com",
                "alias": "prod",
            },
        }
        save_orgs(tmp_path, orgs)
        loaded = load_orgs(tmp_path)
        assert loaded == orgs

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        save_orgs(nested, {"a": {"cache_dir": "/x", "instance_url": "https://x"}})
        assert (nested / "_orgs.json").exists()

    def test_overwrite_existing_registry(self, tmp_path):
        save_orgs(tmp_path, {"old": {"cache_dir": "/old"}})
        save_orgs(tmp_path, {"new": {"cache_dir": "/new"}})
        loaded = load_orgs(tmp_path)
        assert "old" not in loaded
        assert "new" in loaded


# ── Org resolution ───────────────────────────────────────────────────────────

class TestResolveOrgCacheDir:
    """resolve_org_cache_dir alias lookup and fallback."""

    def test_resolves_from_registry(self, tmp_path):
        target = tmp_path / "myorg"
        save_orgs(tmp_path, {
            "myorg": {"cache_dir": str(target), "instance_url": "https://x"},
        })
        result = resolve_org_cache_dir(tmp_path, "myorg")
        assert result == target

    def test_fallback_to_convention(self, tmp_path):
        # No _orgs.json — should return <root>/<alias>
        result = resolve_org_cache_dir(tmp_path, "sandbox")
        assert result == tmp_path / "sandbox"

    def test_unknown_alias_with_registry(self, tmp_path):
        save_orgs(tmp_path, {
            "known": {"cache_dir": str(tmp_path / "known"), "instance_url": "https://x"},
        })
        # Unknown alias falls back to convention
        result = resolve_org_cache_dir(tmp_path, "unknown")
        assert result == tmp_path / "unknown"


# ── Multi-org cache layout ───────────────────────────────────────────────────

class TestMultiOrgCacheLayout:
    """Verify multi-org directory structure works with existing data functions."""

    def _create_org_cache(self, root: Path, alias: str, objects: list[dict]) -> Path:
        """Helper: create a cache subdirectory with objects and registry entry."""
        cache_dir = root / alias
        for obj in objects:
            save_object(cache_dir, obj)
        build_index(cache_dir)
        save_meta(cache_dir, {
            "synced_at": "2026-01-01T00:00:00+00:00",
            "instance_url": f"https://{alias}.my.salesforce.com",
            "objects_synced": len(objects),
        })
        return cache_dir

    def test_two_orgs_isolated(self, tmp_path):
        """Two orgs in same root have independent schemas."""
        obj_a = {"name": "Account", "label": "Account", "custom": False,
                 "fields": [{"name": "Id", "type": "id"}], "child_relationships": []}
        obj_b = {"name": "CustomObj__c", "label": "Custom", "custom": True,
                 "fields": [{"name": "Id", "type": "id"}], "child_relationships": []}

        dir_a = self._create_org_cache(tmp_path, "orgA", [obj_a])
        dir_b = self._create_org_cache(tmp_path, "orgB", [obj_b])

        # Register both
        save_orgs(tmp_path, {
            "orgA": {"cache_dir": str(dir_a), "instance_url": "https://a.sf.com"},
            "orgB": {"cache_dir": str(dir_b), "instance_url": "https://b.sf.com"},
        })

        from src.data.schema_cache import load_object, load_index
        assert load_object(dir_a, "Account") is not None
        assert load_object(dir_a, "CustomObj__c") is None
        assert load_object(dir_b, "CustomObj__c") is not None
        assert load_object(dir_b, "Account") is None

        assert len(load_index(dir_a)) == 1
        assert len(load_index(dir_b)) == 1

    def test_resolve_and_load(self, tmp_path):
        """resolve_org_cache_dir → load_object pipeline."""
        obj = {"name": "Lead", "label": "Lead", "custom": False,
               "fields": [{"name": "Id", "type": "id"}], "child_relationships": []}
        cache_dir = self._create_org_cache(tmp_path, "demo", [obj])
        save_orgs(tmp_path, {
            "demo": {"cache_dir": str(cache_dir), "instance_url": "https://demo.sf.com"},
        })

        resolved = resolve_org_cache_dir(tmp_path, "demo")
        from src.data.schema_cache import load_object
        assert load_object(resolved, "Lead") is not None


# ── MCP server state (unit-level) ────────────────────────────────────────────

class TestMCPOrgState:
    """Test the MCP server's org switching logic at the module level."""

    def test_switch_org_updates_state(self, tmp_path, monkeypatch):
        """switch_org changes _active_cache_dir and returns confirmation."""
        dir_a = tmp_path / "orgA"
        dir_b = tmp_path / "orgB"
        dir_a.mkdir()
        dir_b.mkdir()
        save_meta(dir_a, {"synced_at": "2026-01-01T00:00:00+00:00", "instance_url": "https://a"})
        save_meta(dir_b, {"synced_at": "2026-02-01T00:00:00+00:00", "instance_url": "https://b"})
        save_orgs(tmp_path, {
            "orgA": {"cache_dir": str(dir_a), "instance_url": "https://a"},
            "orgB": {"cache_dir": str(dir_b), "instance_url": "https://b"},
        })

        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))
        monkeypatch.setattr(srv, "_active_cache_dir", str(dir_a))

        result = srv.switch_org("orgB")
        assert "orgB" in result
        assert srv._active_cache_dir == str(dir_b)

    def test_switch_org_unknown_alias(self, tmp_path, monkeypatch):
        save_orgs(tmp_path, {
            "known": {"cache_dir": str(tmp_path / "known"), "instance_url": "https://x"},
        })

        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))

        result = srv.switch_org("nope")
        assert "not found" in result
        assert "known" in result

    def test_list_orgs_shows_active(self, tmp_path, monkeypatch):
        dir_a = tmp_path / "orgA"
        dir_a.mkdir()
        save_orgs(tmp_path, {
            "orgA": {"cache_dir": str(dir_a), "instance_url": "https://a"},
            "orgB": {"cache_dir": str(tmp_path / "orgB"), "instance_url": "https://b"},
        })

        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))
        monkeypatch.setattr(srv, "_active_cache_dir", str(dir_a))

        result = srv.list_orgs()
        assert "orgA" in result
        assert "(ACTIVE)" in result
        assert "orgB" in result

    def test_list_orgs_legacy_mode(self, tmp_path, monkeypatch):
        """No _orgs.json — falls back to legacy single-org display."""
        save_meta(tmp_path, {"instance_url": "https://legacy.sf.com"})

        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))
        monkeypatch.setattr(srv, "_active_cache_dir", str(tmp_path))

        result = srv.list_orgs()
        assert "legacy" in result.lower()
        assert "https://legacy.sf.com" in result
