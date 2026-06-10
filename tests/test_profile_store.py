import os
import stat

from internship_mcp import config, profile_store


class TestEncryptionRoundTrip:
    def test_save_load_roundtrip(self):
        profile = profile_store.default_profile()
        profile["personal"]["full_name"] = "Jane Doe"
        profile_store.save_profile(profile)
        loaded = profile_store.load_profile()
        assert loaded["personal"]["full_name"] == "Jane Doe"

    def test_file_is_encrypted_at_rest(self):
        profile = profile_store.default_profile()
        profile["personal"]["full_name"] = "Jane Doe"
        profile_store.save_profile(profile)
        raw = config.profile_path().read_bytes()
        assert b"Jane Doe" not in raw

    def test_file_mode_600(self):
        profile_store.save_profile(profile_store.default_profile())
        mode = stat.S_IMODE(os.stat(config.profile_path()).st_mode)
        assert mode == 0o600

    def test_missing_file_returns_default(self):
        profile = profile_store.load_profile()
        assert profile["_meta"]["schema_version"] == profile_store.SCHEMA_VERSION


class TestEEODefaults:
    def test_eeo_defaults_decline(self):
        eeo = profile_store.default_profile()["demographics_eeo"]
        assert eeo["gender"] == "decline"
        assert eeo["race_ethnicity"] == ["decline"]
        assert eeo["hispanic_or_latino"] == "decline"
        assert eeo["veteran_status"] == "decline"
        assert eeo["disability_status"] == "decline"

    def test_eeo_never_in_missing_required(self):
        missing = profile_store.missing_required(profile_store.default_profile())
        assert not any("gender" in m.lower() or "race" in m.lower()
                       or "veteran" in m.lower() or "disab" in m.lower()
                       for m in missing)


class TestMissingRequired:
    def test_fresh_profile_missing_everything(self):
        missing = profile_store.missing_required(profile_store.default_profile())
        assert "Full name" in missing
        assert "US citizen?" in missing
        assert "LinkedIn or GitHub URL" in missing

    def test_linkedin_or_github_either_satisfies(self):
        p = profile_store.default_profile()
        p["personal"]["links"]["github"] = "https://github.com/janedoe"
        assert "LinkedIn or GitHub URL" not in profile_store.missing_required(p)

    def test_false_boolean_counts_as_filled(self):
        p = profile_store.default_profile()
        p["work_authorization"]["us_citizen"] = False
        assert "US citizen?" not in profile_store.missing_required(p)


class TestAnswerBank:
    def test_save_and_exact_match(self):
        p = profile_store.default_profile()
        p = profile_store.answer_save(p, "Why do you want to work here?", "Because X.")
        match = profile_store.answer_match(p, "Why do you want to work here?")
        assert match is not None
        assert match[0] == "Because X."
        assert match[1] == 1.0

    def test_fuzzy_match_above_threshold(self):
        p = profile_store.default_profile()
        p = profile_store.answer_save(p, "Why do you want to work at Acme?", "Because X.")
        match = profile_store.answer_match(p, "Why do you want to work at BigCo?")
        assert match is not None  # same question shape, different company

    def test_unrelated_question_returns_none(self):
        p = profile_store.default_profile()
        p = profile_store.answer_save(p, "Why do you want to work here?", "Because X.")
        assert profile_store.answer_match(p, "What is your shirt size?") is None

    def test_resave_updates_existing(self):
        p = profile_store.default_profile()
        p = profile_store.answer_save(p, "Why us?", "Old answer.")
        p = profile_store.answer_save(p, "Why us?", "New answer.")
        assert len(p["answer_bank"]) == 1
        assert p["answer_bank"][0]["answer"] == "New answer."


class TestSetFields:
    def test_deep_merge_preserves_siblings(self):
        p = profile_store.default_profile()
        p["personal"]["email"] = "jane@example.com"
        p = profile_store.set_fields(p, {"personal": {"full_name": "Jane"}})
        assert p["personal"]["email"] == "jane@example.com"
        assert p["personal"]["full_name"] == "Jane"
