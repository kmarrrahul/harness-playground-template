import sys
from types import SimpleNamespace

from app.providers.copilot_service import _find_copilot_cli


def test_find_copilot_cli_prefers_sdk_bundled_binary(monkeypatch, tmp_path):
    pkg_dir = tmp_path / "copilot"
    bin_dir = pkg_dir / "bin"
    bin_dir.mkdir(parents=True)
    expected_name = "copilot.exe" if sys.platform == "win32" else "copilot"
    bundled_bin = bin_dir / expected_name
    bundled_bin.write_text("stub", encoding="utf-8")

    monkeypatch.setitem(sys.modules, "copilot", SimpleNamespace(__file__=str(pkg_dir / "__init__.py")))
    monkeypatch.setattr("app.providers.copilot_service.shutil.which", lambda _name: "/usr/local/bin/copilot")

    path, args = _find_copilot_cli()
    assert path == str(bundled_bin)
    assert args == []


def test_find_copilot_cli_falls_back_when_sdk_binary_missing(monkeypatch, tmp_path):
    pkg_dir = tmp_path / "copilot"
    pkg_dir.mkdir(parents=True)

    monkeypatch.setitem(sys.modules, "copilot", SimpleNamespace(__file__=str(pkg_dir / "__init__.py")))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("app.providers.copilot_service.shutil.which", lambda _name: "/usr/local/bin/copilot")

    path, args = _find_copilot_cli()
    assert path == "/usr/local/bin/copilot"
    assert args == []
