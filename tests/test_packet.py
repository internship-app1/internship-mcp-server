import pytest

from internship_mcp import packet, profile_store, tracker

JOB = {
    "job_hash": "j" * 64,
    "company": "Acme",
    "title": "SWE Intern",
    "apply_link": "https://boards.greenhouse.io/acme/jobs/1",
}


@pytest.fixture()
def filled_profile():
    p = profile_store.default_profile()
    p["personal"]["full_name"] = "Jane Doe"
    p["personal"]["email"] = "jane@example.com"
    p["personal"]["phone"] = "555-123-4567"
    p["personal"]["address"].update({"city": "San Jose", "state": "CA"})
    p["personal"]["links"]["linkedin"] = "https://linkedin.com/in/janedoe"
    p["work_authorization"]["us_citizen"] = True
    p["work_authorization"]["work_authorized_in_us"] = True
    p["work_authorization"]["requires_sponsorship_now_or_future"] = False
    p["logistics"]["willing_to_relocate"] = True
    p["logistics"]["earliest_start_date"] = "June 2026"
    profile_store.save_profile(p)
    return p


class TestAtsDetection:
    @pytest.mark.parametrize("url,expected", [
        ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
        ("https://jobs.lever.co/acme/abc", "lever"),
        ("https://jobs.ashbyhq.com/acme/abc", "ashby"),
        ("https://acme.wd5.myworkdayjobs.com/careers/job/1", "workday"),
        ("https://careers.acme.com/apply", "other"),
        ("", "other"),
    ])
    def test_detect(self, url, expected):
        assert packet.detect_ats_type(url) == expected


class TestSubjectiveDetection:
    @pytest.mark.parametrize("label", [
        "Why Acme?", "What is your proudest achievement?",
        "Tell us about a project you loved", "Cover letter",
        "Describe a time you failed",
    ])
    def test_subjective(self, label):
        assert packet.is_subjective(label)

    @pytest.mark.parametrize("label", ["First name", "Email", "Phone number"])
    def test_objective(self, label):
        assert not packet.is_subjective(label)


class TestBuildPacket:
    def test_profile_fields_filled_high_confidence(self, filled_profile):
        result = packet.build_packet(
            JOB,
            ["First name", "Email", "Are you authorized to work in the US?",
             "Will you require sponsorship?"],
            "/tmp/resume.pdf",
        )
        by_label = {f["label"]: f for f in result["fields"]}
        assert by_label["First name"]["value"] == "Jane"
        assert by_label["Email"]["value"] == "jane@example.com"
        assert by_label["Are you authorized to work in the US?"]["value"] == "Yes"
        assert by_label["Will you require sponsorship?"]["value"] == "No"
        assert all(f["confidence"] == "high" for f in result["fields"])
        assert result["ats_type"] == "greenhouse"

    def test_eeo_defaults_to_decline_never_invented(self, filled_profile):
        result = packet.build_packet(
            JOB, ["Gender", "Veteran status", "Disability status"], "/tmp/r.pdf"
        )
        for f in result["fields"]:
            assert f["value"] == "Decline to self-identify"
            assert f["source"] == "profile_eeo"
        assert result["needs_user_input"] == []

    def test_subjective_question_routed_to_user(self, filled_profile):
        result = packet.build_packet(JOB, ["Why do you want to join Acme?"], "/tmp/r.pdf")
        assert result["fields"] == []
        assert len(result["needs_user_input"]) == 1
        assert result["needs_user_input"][0]["reason"] == "subjective/authentic"

    def test_answer_bank_reuse(self, filled_profile):
        p = profile_store.load_profile()
        p = profile_store.answer_save(
            p, "Why do you want to join Acme?", "I admire the dev tooling team."
        )
        profile_store.save_profile(p)
        result = packet.build_packet(JOB, ["Why do you want to join Acme?"], "/tmp/r.pdf")
        assert result["fields"][0]["value"] == "I admire the dev tooling team."
        assert result["fields"][0]["source"] == "answer_bank"

    def test_explicit_answers_take_precedence(self, filled_profile):
        result = packet.build_packet(
            JOB, ["Why Acme?"], "/tmp/r.pdf",
            answers={"Why Acme?": "User-provided reason."},
        )
        assert result["fields"][0]["value"] == "User-provided reason."

    def test_dedup_refuses_submitted_job(self, filled_profile):
        tracker.record(JOB["job_hash"], "submitted")
        with pytest.raises(RuntimeError, match="already SUBMITTED"):
            packet.build_packet(JOB, ["Email"], "/tmp/r.pdf")
        # force=True overrides
        result = packet.build_packet(JOB, ["Email"], "/tmp/r.pdf", force=True)
        assert result["fields"]
