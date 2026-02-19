"""Tests for refresh_object MCP tool, key_fields_only parameter, and sf_api module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.data import sf_api
from src.data.schema_cache import (
    build_index,
    load_index,
    load_object,
    save_meta,
    save_object,
    save_orgs,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_RAW_DESCRIBE = {
    "name": "Account",
    "label": "Account",
    "labelPlural": "Accounts",
    "custom": False,
    "fields": [
        {
            "name": "Id",
            "label": "Account ID",
            "type": "id",
            "nillable": False,
            "defaultedOnCreate": True,
            "externalId": False,
            "referenceTo": [],
            "picklistValues": [],
        },
        {
            "name": "Name",
            "label": "Account Name",
            "type": "string",
            "nillable": False,
            "defaultedOnCreate": False,
            "externalId": False,
            "referenceTo": [],
            "picklistValues": [],
        },
        {
            "name": "ParentId",
            "label": "Parent Account ID",
            "type": "reference",
            "nillable": True,
            "defaultedOnCreate": False,
            "externalId": False,
            "referenceTo": ["Account"],
            "picklistValues": [],
        },
    ],
    "childRelationships": [
        {
            "childSObject": "Contact",
            "field": "AccountId",
            "relationshipName": "Contacts",
        }
    ],
}


def _make_large_object(field_count: int = 50) -> dict:
    """Create a normalised object dict with many fields."""
    fields = [{"name": "Id", "type": "id", "label": "ID", "required": False, "external_id": False, "reference_to": [], "picklist_values": []}]
    fields.append({"name": "OwnerId", "type": "reference", "label": "Owner", "required": True, "external_id": False, "reference_to": ["User"], "picklist_values": []})
    fields.append({"name": "ExternalKey__c", "type": "string", "label": "External Key", "required": False, "external_id": True, "reference_to": [], "picklist_values": []})
    for i in range(field_count - 3):
        fields.append({
            "name": f"Field_{i}__c",
            "type": "string",
            "label": f"Field {i}",
            "required": False,
            "external_id": False,
            "reference_to": [],
            "picklist_values": [],
        })
    return {
        "name": "BigObject__c",
        "label": "Big Object",
        "custom": True,
        "fields": fields,
        "child_relationships": [],
    }


# ── sf_api.normalise tests ───────────────────────────────────────────────────

class TestNormalise:
    def test_normalise_basic_structure(self):
        result = sf_api.normalise(SAMPLE_RAW_DESCRIBE)
        assert result["name"] == "Account"
        assert result["label"] == "Account"
        assert result["custom"] is False
        assert len(result["fields"]) == 3
        assert len(result["child_relationships"]) == 1

    def test_normalise_field_types_lowered(self):
        raw = {
            "name": "Test",
            "fields": [{"name": "X", "label": "X", "type": "STRING", "nillable": True}],
            "childRelationships": [],
        }
        result = sf_api.normalise(raw)
        assert result["fields"][0]["type"] == "string"

    def test_normalise_required_logic(self):
        result = sf_api.normalise(SAMPLE_RAW_DESCRIBE)
        id_field = next(f for f in result["fields"] if f["name"] == "Id")
        name_field = next(f for f in result["fields"] if f["name"] == "Name")
        # Id is not nillable but defaultedOnCreate → not required
        assert id_field["required"] is False
        # Name is not nillable and not defaultedOnCreate → required
        assert name_field["required"] is True

    def test_normalise_reference_to(self):
        result = sf_api.normalise(SAMPLE_RAW_DESCRIBE)
        parent_field = next(f for f in result["fields"] if f["name"] == "ParentId")
        assert parent_field["reference_to"] == ["Account"]
        assert parent_field["type"] == "reference"

    def test_normalise_child_relationships(self):
        result = sf_api.normalise(SAMPLE_RAW_DESCRIBE)
        assert result["child_relationships"][0]["child_sobject"] == "Contact"
        assert result["child_relationships"][0]["field"] == "AccountId"


# ── sf_api.get_session tests ────────────────────────────────────────────────

class TestGetSession:
    def test_get_session_calls_sf_cli(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "result": {
                "instanceUrl": "https://test.my.salesforce.com/",
                "accessToken": "tok123",
                "username": "user@test.com",
            }
        })
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            url, token = sf_api.get_session("myorg")
            mock_run.assert_called_once_with(
                ["sf", "org", "display", "-o", "myorg", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            assert url == "https://test.my.salesforce.com"
            assert token == "tok123"

    def test_get_session_strips_trailing_slash(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "result": {
                "instanceUrl": "https://test.my.salesforce.com/",
                "accessToken": "tok",
            }
        })
        with patch("subprocess.run", return_value=mock_result):
            url, _ = sf_api.get_session("x")
            assert not url.endswith("/")

    def test_get_session_raises_on_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "{}"
        mock_result.stderr = "auth expired"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="sf org display failed"):
                sf_api.get_session("badorg")

    def test_get_session_raises_on_missing_cli(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="sf.*CLI not found"):
                sf_api.get_session("any")


# ── key_fields_only tests ────────────────────────────────────────────────────

class TestKeyFieldsOnly:
    def test_key_fields_only_truncates_large_object(self, tmp_path, monkeypatch):
        obj = _make_large_object(50)
        save_object(tmp_path, obj)
        build_index(tmp_path)

        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))
        monkeypatch.setattr(srv, "_active_cache_dir", str(tmp_path))

        result = srv.get_object_schema("BigObject__c", key_fields_only=True)
        assert "Key Fields" in result
        assert "of 50 total" in result
        assert "omitted" in result
        # Should not contain all 50 fields
        field_lines = [l for l in result.split("\n") if l.startswith("  Field_")]
        assert len(field_lines) < 50

    def test_key_fields_only_small_object_no_truncation(self, tmp_path, monkeypatch):
        obj = {
            "name": "SmallObj__c",
            "label": "Small Object",
            "custom": True,
            "fields": [
                {"name": "Id", "type": "id", "label": "ID", "required": False, "external_id": False, "reference_to": [], "picklist_values": []},
                {"name": "Name", "type": "string", "label": "Name", "required": True, "external_id": False, "reference_to": [], "picklist_values": []},
            ],
            "child_relationships": [],
        }
        save_object(tmp_path, obj)
        build_index(tmp_path)

        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))
        monkeypatch.setattr(srv, "_active_cache_dir", str(tmp_path))

        result = srv.get_object_schema("SmallObj__c", key_fields_only=True)
        assert "Key Fields" in result
        assert "omitted" not in result

    def test_default_returns_all_fields(self, tmp_path, monkeypatch):
        obj = _make_large_object(50)
        save_object(tmp_path, obj)
        build_index(tmp_path)

        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))
        monkeypatch.setattr(srv, "_active_cache_dir", str(tmp_path))

        result = srv.get_object_schema("BigObject__c", key_fields_only=False)
        assert "Fields (50):" in result
        assert "omitted" not in result


# ── refresh_object tests ─────────────────────────────────────────────────────

class TestRefreshObject:
    def _setup_org(self, tmp_path, monkeypatch):
        """Set up a registered org with an existing cached object."""
        cache_dir = tmp_path / "testorg"
        cache_dir.mkdir()
        old_obj = {
            "name": "Account",
            "label": "Account",
            "custom": False,
            "fields": [{"name": "Id", "type": "id", "label": "ID", "required": False, "external_id": False, "reference_to": [], "picklist_values": []}],
            "child_relationships": [],
        }
        save_object(cache_dir, old_obj)
        build_index(cache_dir)
        save_meta(cache_dir, {"synced_at": "2026-01-01T00:00:00+00:00", "instance_url": "https://test.sf.com"})
        save_orgs(tmp_path, {
            "testorg": {"cache_dir": str(cache_dir), "instance_url": "https://test.sf.com"},
        })

        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))
        monkeypatch.setattr(srv, "_active_cache_dir", str(cache_dir))
        return cache_dir

    def test_refresh_updates_cache(self, tmp_path, monkeypatch):
        cache_dir = self._setup_org(tmp_path, monkeypatch)

        # Before refresh: Account has 1 field
        old = load_object(cache_dir, "Account")
        assert len(old["fields"]) == 1

        import src.mcp.server as srv
        with patch.object(sf_api, "get_session", return_value=("https://test.sf.com", "tok")):
            with patch.object(sf_api, "describe_object", return_value=SAMPLE_RAW_DESCRIBE):
                result = srv.refresh_object("Account")

        assert "Refreshed" in result
        assert "3 fields" in result

        # After refresh: Account has 3 fields
        updated = load_object(cache_dir, "Account")
        assert len(updated["fields"]) == 3

        # Index also updated
        index = load_index(cache_dir)
        acct = next(o for o in index if o["name"] == "Account")
        assert acct["field_count"] == 3

    def test_refresh_no_active_org(self, tmp_path, monkeypatch):
        """Legacy mode (no _orgs.json) returns helpful error."""
        import src.mcp.server as srv
        monkeypatch.setattr(srv, "CACHE_ROOT", str(tmp_path))
        monkeypatch.setattr(srv, "_active_cache_dir", str(tmp_path))

        result = srv.refresh_object("Account")
        assert "Cannot refresh" in result

    def test_refresh_api_error(self, tmp_path, monkeypatch):
        """API error returns message without corrupting cache."""
        cache_dir = self._setup_org(tmp_path, monkeypatch)

        import src.mcp.server as srv
        with patch.object(sf_api, "get_session", return_value=("https://test.sf.com", "tok")):
            with patch.object(sf_api, "describe_object", side_effect=Exception("404 Not Found")):
                result = srv.refresh_object("BadObject__c")

        assert "failed" in result.lower()
        # Original Account should still be intact
        assert load_object(cache_dir, "Account") is not None
