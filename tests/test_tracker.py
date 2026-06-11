import pytest

from internship_mcp import tracker


class TestTracker:
    def test_record_and_status(self):
        tracker.record("h1", "matched", company="Acme", title="SWE Intern")
        row = tracker.get_status("h1")
        assert row["status"] == "matched"
        assert row["company"] == "Acme"

    def test_upsert_keeps_created_fields(self):
        tracker.record("h1", "matched", company="Acme")
        tracker.record("h1", "prefilled")
        row = tracker.get_status("h1")
        assert row["status"] == "prefilled"
        assert row["company"] == "Acme"  # not blanked by the update

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            tracker.record("h1", "applied")  # not in the enum

    def test_submitted_sets_timestamp_and_is_submitted(self):
        tracker.record("h2", "submitted")
        assert tracker.is_submitted("h2")
        assert tracker.get_status("h2")["submitted_at"] is not None
        assert not tracker.is_submitted("never-seen")

    def test_list_filter_by_status(self):
        tracker.record("h1", "matched")
        tracker.record("h2", "submitted")
        assert {r["job_hash"] for r in tracker.list_applications("submitted")} == {"h2"}
        assert len(tracker.list_applications()) == 2

    def test_jobs_not_applied_splits_correctly(self):
        tracker.record("applied-hash", "submitted", company="Acme")
        from internship_mcp.__main__ import jobs_not_applied
        result = jobs_not_applied(["applied-hash", "new-hash-1", "new-hash-2"])
        assert result["already_applied"] == ["applied-hash"]
        assert set(result["unapplied"]) == {"new-hash-1", "new-hash-2"}
