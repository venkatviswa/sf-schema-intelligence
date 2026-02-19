"""Tests for src.core.diff — deterministic schema comparison."""
from __future__ import annotations

from src.core.diff import FieldChange, compare_snapshots


class TestCompareSnapshots:
    """High-level snapshot comparison tests."""

    def test_added_object_detected(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        assert "HealthCloudGA__CareMetric__c" in result.added_objects

    def test_no_removed_objects(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        assert result.removed_objects == []

    def test_identical_snapshots_produce_empty_diff(self, snapshot_v1):
        result = compare_snapshots(snapshot_v1, snapshot_v1)
        assert result.added_objects == []
        assert result.removed_objects == []
        assert result.modified_objects == {}
        assert result.breaking_candidates == []

    def test_summary_counts(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        assert result.summary["objects_added"] == 1
        assert result.summary["objects_removed"] == 0
        assert result.summary["objects_modified"] > 0
        assert result.summary["total_field_changes"] > 0


class TestFieldAdded:
    """Field addition detection."""

    def test_new_field_detected_on_care_plan(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        care_plan_added = result.added_fields.get("HealthCloudGA__CarePlan__c", [])
        field_names = [c.field_name for c in care_plan_added]
        assert "HealthCloudGA__ReviewDate__c" in field_names

    def test_added_field_is_non_breaking(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        care_plan_added = result.added_fields.get("HealthCloudGA__CarePlan__c", [])
        for c in care_plan_added:
            if c.field_name == "HealthCloudGA__ReviewDate__c":
                assert c.severity == "NON_BREAKING"
                assert c.change_type == "ADDED"

    def test_new_required_field_added_to_account(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        acct_added = result.added_fields.get("Account", [])
        field_names = [c.field_name for c in acct_added]
        assert "HealthCloudGA__TaxId__c" in field_names


class TestFieldRemoved:
    """Field removal detection."""

    def test_removed_field_detected_on_account(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        acct_removed = result.removed_fields.get("Account", [])
        field_names = [c.field_name for c in acct_removed]
        assert "LastModifiedDate" in field_names

    def test_removed_field_is_breaking(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        acct_removed = result.removed_fields.get("Account", [])
        for c in acct_removed:
            if c.field_name == "LastModifiedDate":
                assert c.severity == "BREAKING"
                assert c.change_type == "REMOVED"


class TestTypeChanged:
    """Field type change detection."""

    def test_type_change_detected(self, snapshot_v1, snapshot_v2):
        """Account.NumberOfEmployees changed from int -> string."""
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        acct_types = result.type_changes.get("Account", [])
        field_names = [c.field_name for c in acct_types]
        assert "NumberOfEmployees" in field_names

    def test_incompatible_type_change_is_breaking(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        acct_types = result.type_changes.get("Account", [])
        for c in acct_types:
            if c.field_name == "NumberOfEmployees":
                assert c.severity == "BREAKING"
                assert c.old_value == "int"
                assert c.new_value == "string"


class TestRequiredChanged:
    """Required flag change detection."""

    def test_required_added_is_breaking(self, snapshot_v1, snapshot_v2):
        """CarePlan.Status__c changed from optional to required."""
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        cp_diff = result.modified_objects.get("HealthCloudGA__CarePlan__c")
        assert cp_diff is not None
        req_changes = [
            c for c in cp_diff.other_changes
            if c.change_type == "REQUIRED_CHANGED"
        ]
        status_change = [c for c in req_changes if c.field_name == "HealthCloudGA__Status__c"]
        assert len(status_change) == 1
        assert status_change[0].severity == "BREAKING"
        assert status_change[0].old_value is False
        assert status_change[0].new_value is True


class TestBreakingCandidates:
    """Breaking change candidate aggregation."""

    def test_breaking_candidates_populated(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        assert len(result.breaking_candidates) > 0
        severities = {c.severity for c in result.breaking_candidates}
        assert severities == {"BREAKING"}

    def test_breaking_includes_removed_field(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        removed = [c for c in result.breaking_candidates if c.change_type == "REMOVED"]
        assert any(c.field_name == "LastModifiedDate" for c in removed)


class TestOutputFormats:
    """Serialisation tests."""

    def test_as_dict_is_json_serialisable(self, snapshot_v1, snapshot_v2):
        import json
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        d = result.as_dict()
        json.dumps(d)  # should not raise

    def test_as_text_report_is_string(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        report = result.as_text_report()
        assert isinstance(report, str)
        assert "Schema Diff Report" in report
        assert "Breaking Change Candidates" in report


class TestEdgeCases:
    """Edge cases for the diff engine."""

    def test_empty_snapshot_vs_populated(self, snapshot_v1):
        result = compare_snapshots({}, snapshot_v1)
        assert set(result.added_objects) == set(snapshot_v1.keys())
        assert result.removed_objects == []

    def test_populated_vs_empty_snapshot(self, snapshot_v1):
        result = compare_snapshots(snapshot_v1, {})
        assert result.added_objects == []
        assert set(result.removed_objects) == set(snapshot_v1.keys())

    def test_empty_vs_empty(self):
        result = compare_snapshots({}, {})
        assert result.added_objects == []
        assert result.removed_objects == []
        assert result.summary["total_field_changes"] == 0
