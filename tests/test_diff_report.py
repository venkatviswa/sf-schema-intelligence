"""Tests for snapshot archival and Markdown diff reports."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.core.diff import DiffResult, as_markdown_report, compare_snapshots
from src.data.schema_cache import (
    archive_snapshot,
    load_latest_archive,
    load_meta,
    load_snapshot,
    save_meta,
    save_object,
)


# ── archive_snapshot tests ────────────────────────────────────────────────────

class TestArchiveSnapshot:
    """Tests for schema_cache.archive_snapshot."""

    def test_creates_dated_directory(self, v1_dir, tmp_path):
        # Copy v1 fixtures to tmp so we don't modify test data
        cache = tmp_path / "cache"
        shutil.copytree(v1_dir, cache)
        archive_dir = archive_snapshot(cache)
        assert archive_dir.exists()
        assert archive_dir.name == "2025-01-15"  # from _meta.json synced_at
        assert (archive_dir / "Account.json").exists()
        assert (archive_dir / "_meta.json").exists()
        assert (archive_dir / "_index.json").exists()

    def test_default_archive_root(self, v1_dir, tmp_path):
        cache = tmp_path / "cache"
        shutil.copytree(v1_dir, cache)
        archive_dir = archive_snapshot(cache)
        assert "_snapshots" in str(archive_dir)
        assert archive_dir.parent.name == "_snapshots"

    def test_custom_archive_root(self, v1_dir, tmp_path):
        cache = tmp_path / "cache"
        shutil.copytree(v1_dir, cache)
        custom_root = tmp_path / "my_archives"
        archive_dir = archive_snapshot(cache, archive_root=custom_root)
        assert str(custom_root) in str(archive_dir)

    def test_missing_cache_dir(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            archive_snapshot(tmp_path / "nonexistent")

    def test_missing_meta(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        # No _meta.json
        save_object(cache, {"name": "Account", "fields": []})
        with pytest.raises(ValueError, match="_meta.json"):
            archive_snapshot(cache)

    def test_copies_all_json_files(self, v1_dir, tmp_path):
        cache = tmp_path / "cache"
        shutil.copytree(v1_dir, cache)
        archive_dir = archive_snapshot(cache)
        original_jsons = set(f.name for f in cache.glob("*.json"))
        archived_jsons = set(f.name for f in archive_dir.glob("*.json"))
        assert original_jsons == archived_jsons


# ── load_latest_archive tests ────────────────────────────────────────────────

class TestLoadLatestArchive:
    """Tests for schema_cache.load_latest_archive."""

    def test_returns_none_when_no_archives(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        path, snapshot = load_latest_archive(cache)
        assert path is None
        assert snapshot == {}

    def test_loads_latest(self, v1_dir, v2_dir, tmp_path):
        cache = tmp_path / "cache"
        shutil.copytree(v1_dir, cache)

        # Archive v1
        archive_snapshot(cache)

        # Overwrite with v2 data and update meta
        for f in v2_dir.glob("*.json"):
            shutil.copy2(f, cache / f.name)

        # Load the latest archive — should be v1
        path, snap = load_latest_archive(cache)
        assert path is not None
        assert "Account" in snap

    def test_picks_most_recent_date(self, v1_dir, tmp_path):
        cache = tmp_path / "cache"
        shutil.copytree(v1_dir, cache)
        snapshots_root = cache / "_snapshots"

        # Create two dated dirs manually
        (snapshots_root / "2025-01-10").mkdir(parents=True)
        (snapshots_root / "2025-01-20").mkdir(parents=True)
        # Copy an object into the newer one
        shutil.copy2(v1_dir / "Account.json", snapshots_root / "2025-01-20" / "Account.json")

        path, snap = load_latest_archive(cache)
        assert path is not None
        assert path.name == "2025-01-20"
        assert "Account" in snap


# ── as_markdown_report tests ─────────────────────────────────────────────────

class TestAsMarkdownReport:
    """Tests for diff.as_markdown_report."""

    def test_no_changes(self):
        result = DiffResult(summary={
            "objects_added": 0, "objects_removed": 0,
            "objects_modified": 0, "total_field_changes": 0,
            "breaking_candidates": 0, "fields_added": 0,
            "fields_removed": 0, "type_changes": 0,
            "relationship_changes": 0,
        })
        report = as_markdown_report(result)
        assert "# Schema Diff Report" in report
        assert "**No changes detected.**" in report

    def test_with_meta_dates(self):
        result = DiffResult(summary={
            "objects_added": 0, "objects_removed": 0,
            "objects_modified": 0, "total_field_changes": 0,
            "breaking_candidates": 0, "fields_added": 0,
            "fields_removed": 0, "type_changes": 0,
            "relationship_changes": 0,
        })
        meta_before = {"synced_at": "2025-01-15T10:00:00", "instance_url": "https://test.sf.com"}
        meta_after = {"synced_at": "2025-01-16T10:00:00", "instance_url": "https://test.sf.com"}
        report = as_markdown_report(result, meta_before, meta_after)
        assert "2025-01-15" in report
        assert "2025-01-16" in report
        assert "test.sf.com" in report

    def test_with_changes(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        report = as_markdown_report(result)
        assert "# Schema Diff Report" in report
        assert "## Summary" in report
        # v2 adds HealthCloudGA__CareMetric__c
        assert "Added Objects" in report
        assert "HealthCloudGA__CareMetric__c" in report

    def test_breaking_changes_section(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        if result.breaking_candidates:
            report = as_markdown_report(result)
            assert "## Breaking Changes" in report

    def test_modified_objects_section(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        if result.modified_objects:
            report = as_markdown_report(result)
            assert "## Modified Objects" in report

    def test_report_is_valid_markdown(self, snapshot_v1, snapshot_v2):
        result = compare_snapshots(snapshot_v1, snapshot_v2)
        report = as_markdown_report(result)
        # Basic Markdown structure checks
        assert report.startswith("# ")
        assert report.endswith("\n")
        # Table separators present
        assert "|--------|" in report
