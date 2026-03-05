"""Tests for src/core/workbook.py — Markdown data integrity workbook generation."""
from __future__ import annotations

import pytest

from src.core.workbook import generate_workbook
from src.data.schema_cache import load_index, load_meta, load_snapshot


class TestGenerateWorkbook:
    """Tests for the main generate_workbook function."""

    def test_returns_string(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        meta = load_meta(v1_dir)
        result = generate_workbook(snapshot_v1, index, meta)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_all_sections(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        meta = load_meta(v1_dir)
        result = generate_workbook(snapshot_v1, index, meta)
        assert "# Data Integrity Workbook" in result
        assert "## Object Inventory" in result
        assert "## Field Dictionary" in result
        assert "## Relationship Map" in result
        assert "## Aggregate Metrics" in result

    def test_executive_summary_has_meta(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        meta = load_meta(v1_dir)
        result = generate_workbook(snapshot_v1, index, meta)
        assert "test-org.my.salesforce.com" in result
        assert "v60.0" in result

    def test_executive_summary_counts(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        meta = load_meta(v1_dir)
        result = generate_workbook(snapshot_v1, index, meta)
        # Should show total objects (6), custom (4), standard (2)
        assert "| Total Objects | 6 |" in result
        assert "| Standard Objects | 2 |" in result
        assert "| Custom Objects | 4 |" in result

    def test_no_meta(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        result = generate_workbook(snapshot_v1, index, None)
        assert "# Data Integrity Workbook" in result
        # Should not crash, just omit org info
        assert "**Org:**" not in result

    def test_filter_objects(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        meta = load_meta(v1_dir)
        result = generate_workbook(snapshot_v1, index, meta, objects=["Account"])
        # Should only show Account, not Contact or custom objects
        assert "### Account" in result
        assert "### Contact" not in result
        assert "| Total Objects | 1 |" in result

    def test_no_picklists(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        meta = load_meta(v1_dir)
        result_with = generate_workbook(snapshot_v1, index, meta, include_picklists=True)
        result_without = generate_workbook(snapshot_v1, index, meta, include_picklists=False)
        assert "Picklist Values" in result_with
        assert "Picklist Values" not in result_without

    def test_empty_snapshot(self):
        result = generate_workbook({}, [], None)
        assert "# Data Integrity Workbook" in result
        assert "| Total Objects | 0 |" in result


class TestObjectInventory:
    """Tests for the object inventory section."""

    def test_all_objects_listed(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        meta = load_meta(v1_dir)
        result = generate_workbook(snapshot_v1, index, meta)
        assert "| Account |" in result
        assert "| Contact |" in result
        assert "| HealthCloudGA__CarePlan__c |" in result

    def test_custom_flag(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        result = generate_workbook(snapshot_v1, index, None)
        # Look in the Object Inventory section only (before Field Dictionary)
        inventory_section = result.split("## Field Dictionary")[0]
        lines = inventory_section.split("\n")
        for line in lines:
            if "| Account |" in line and "Object API Name" not in line:
                assert "| No |" in line
            if "| HealthCloudGA__CarePlan__c |" in line:
                assert "| Yes |" in line


class TestFieldDictionary:
    """Tests for the field dictionary section."""

    def test_field_headers(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        result = generate_workbook(snapshot_v1, index, None)
        assert "| Field | Label | Type | Required |" in result

    def test_field_rows(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        result = generate_workbook(snapshot_v1, index, None)
        # Account has an Id field
        assert "| Id |" in result


class TestRelationshipMap:
    """Tests for the relationship map section."""

    def test_relationship_headers(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        result = generate_workbook(snapshot_v1, index, None)
        assert "| Source Object | Field | Type | Target Object |" in result


class TestAggregateMetrics:
    """Tests for the aggregate metrics section."""

    def test_field_type_distribution(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        result = generate_workbook(snapshot_v1, index, None)
        assert "### Field Type Distribution" in result
        assert "| Field Type | Count | Percentage |" in result

    def test_most_connected_objects(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        result = generate_workbook(snapshot_v1, index, None)
        assert "### Most Connected Objects" in result

    def test_custom_fields_section(self, snapshot_v1, v1_dir):
        index = load_index(v1_dir)
        result = generate_workbook(snapshot_v1, index, None)
        # Custom objects have __c fields
        assert "### Objects With Most Custom Fields" in result
