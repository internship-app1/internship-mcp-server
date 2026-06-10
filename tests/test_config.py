"""compile_setup onboarding info + COMPILE mode resolution."""
from internship_mcp import config


class TestCompileSetupInfo:
    def test_shape(self):
        info = config.compile_setup_info()
        assert set(info) == {"pdflatex_installed", "mode", "remote_quota", "install_commands"}
        assert set(info["install_commands"]) == {"macos", "debian_ubuntu", "windows"}
        assert "15" in info["remote_quota"]

    def test_pdflatex_flag_follows_path(self, monkeypatch):
        monkeypatch.setattr(config.shutil, "which", lambda _: "/usr/bin/pdflatex")
        assert config.compile_setup_info()["pdflatex_installed"] is True
        assert config.compile_setup_info()["mode"] == "local"  # COMPILE=auto default
        monkeypatch.setattr(config.shutil, "which", lambda _: None)
        assert config.compile_setup_info()["pdflatex_installed"] is False
        assert config.compile_setup_info()["mode"] == "remote"

    def test_explicit_compile_env_wins(self, monkeypatch):
        monkeypatch.setenv("COMPILE", "remote")
        monkeypatch.setattr(config.shutil, "which", lambda _: "/usr/bin/pdflatex")
        assert config.compile_setup_info()["mode"] == "remote"


class TestCompileChoicePersistence:
    def test_choice_recorded_once_via_profile_set(self):
        from internship_mcp import profile_store

        p = profile_store.default_profile()
        assert p["_meta"].get("compile_choice") is None
        p = profile_store.set_fields(p, {"_meta": {"compile_choice": "local"}})
        profile_store.save_profile(p)
        assert profile_store.load_profile()["_meta"]["compile_choice"] == "local"
