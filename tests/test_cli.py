import subprocess
import sys

from mutator.cli import parse_args, run
from mutator.runner import CommandResult


def test_lines_option_parses_positive_numbers():
    options = parse_args(["--lines", "2, 4", "src/demo.py"])
    assert options.lines == {2, 4}


def test_changed_selects_a_dirty_source_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "src" / "demo.py"
    path.parent.mkdir()
    path.write_text("def place(x):\n    return x > 0\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "src/demo.py"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    code = run(["--scan", "--no-coverage", "--changed", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert "demo.py:2" in captured.out


def test_a_directory_argument_skips_a_named_test_file(tmp_path, capsys):
    src = tmp_path / "pkg" / "app.py"
    src.parent.mkdir()
    src.write_text("def place(x):\n    return x > 0\n", encoding="utf-8")
    test = tmp_path / "pkg" / "test_app.py"
    test.write_text("def test_place():\n    assert True\n", encoding="utf-8")
    code = run(
        ["--scan", "--no-coverage", "--root", str(tmp_path), str(tmp_path / "pkg"), str(test)]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "Skipping test file" in captured.err
    assert "app.py:2" in captured.out


def test_help_and_conflicting_flags():
    help_options = parse_args(["--help"])
    assert help_options.exit_code == 0
    assert "uml-viewer" in help_options.message
    assert "__pycache__" in help_options.message
    assert "testdata" in help_options.message
    conflict = parse_args(["--mutate-all", "--since-last-run", "src/demo.py"])
    assert conflict.exit_code == 1
    assert run(["--help"]) == 0


def test_scan_lists_sites_without_writing_metrics(tmp_path, monkeypatch):
    path = tmp_path / "src" / "demo.py"
    path.parent.mkdir()
    path.write_text("def place(x):\n    return x > 0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = run(["--scan", "--no-coverage", "--root", str(tmp_path), "src/demo.py"])
    assert code == 0
    assert not (tmp_path / ".metrics").exists()


def test_real_python_mutants_update_the_snapshot(tmp_path, capsys):
    path = tmp_path / "src" / "demo.py"
    path.parent.mkdir()
    path.write_text(
        "def add(a, b):\n"
        "    if a > 0:\n"
        "        return a + b\n"
        "    return 0\n",
        encoding="utf-8",
    )
    command = (
        f"{sys.executable} -c \"import sys; sys.path.insert(0, 'src'); "
        "from demo import add; raise SystemExit(0 if add(2, 3) == 5 else 1)\""
    )
    code = run(
        [
            "--no-coverage",
            "--mutate-all",
            "--root",
            str(tmp_path),
            "--test-command",
            command,
            "src/demo.py",
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "SURVIVED" in captured.out
    assert "KILLED" in captured.out
    snapshot = tmp_path / ".metrics" / "mutate" / "demo.edn"
    assert snapshot.is_file()
    text = snapshot.read_text(encoding="utf-8")
    assert ":namespace \"demo\"" in text
    assert ":id \"defn/add\"" in text
    assert path.read_text(encoding="utf-8").startswith("def add")


def test_a_failed_coverage_command_does_not_read_the_report(tmp_path, capsys):
    path = tmp_path / "src" / "app.py"
    path.parent.mkdir()
    path.write_text("def place(x):\n    return x > 0\n", encoding="utf-8")
    report = tmp_path / "target" / "coverage" / "python" / "lcov.info"
    report.parent.mkdir(parents=True)
    report.write_text("SF:src/app.py\nDA:1,1\nDA:2,1\nend_of_record\n", encoding="utf-8")
    code = run(
        [
            "--root",
            str(tmp_path),
            "--coverage-command",
            "exit 3",
            "--test-command",
            "false",
            "src/app.py",
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "will not be read" in captured.err
    assert "Baseline failed" not in captured.err
    assert path.read_text(encoding="utf-8").startswith("def place")


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_changed_since_selects_the_branch_scope_from_the_merge_base(tmp_path, monkeypatch, capsys):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    source = "def {}(x):\n    return x > 0\n"
    for name in ("base", "edited", "gone"):
        _write(tmp_path, f"src/{name}.py", source.format(name))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "switch", "-c", "feature")
    _write(tmp_path, "src/committed.py", source.format("committed"))
    _git(tmp_path, "rm", "-q", "src/gone.py")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "feature")
    _git(tmp_path, "switch", "main")
    _write(tmp_path, "src/upstream_only.py", source.format("upstream_only"))
    _write(tmp_path, "src/base.py", "def base(x):\n    return x >= 0\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "main moves on")
    _git(tmp_path, "switch", "feature")
    _write(tmp_path, "src/staged.py", source.format("staged"))
    _git(tmp_path, "add", "src/staged.py")
    _write(tmp_path, "src/edited.py", "def edited(x):\n    return x < 0\n")
    _write(tmp_path, "src/untracked.py", source.format("untracked"))
    _write(tmp_path, "src/test_untracked.py", "def test_untracked():\n    assert 1 > 0\n")
    monkeypatch.chdir(tmp_path)

    code = run(["--scan", "--no-coverage", "--changed-since", "main", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    for name in ("committed", "staged", "edited", "untracked"):
        assert f"{name}.py:2" in out
    # main's later commits, unchanged files, deletions, and tests are out of scope.
    for name in ("upstream_only", "base", "gone", "test_untracked"):
        assert f"{name}.py" not in out


def test_changed_since_an_unknown_ref_returns_gits_status(tmp_path, monkeypatch, capsys):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _write(tmp_path, "src/demo.py", "def place(x):\n    return x > 0\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    monkeypatch.chdir(tmp_path)

    code = run(["--scan", "--no-coverage", "--changed-since", "no-such-ref", "--root", str(tmp_path)])

    captured = capsys.readouterr()
    assert code != 0
    assert "demo.py" not in captured.out
    assert captured.err.strip()


def test_changed_since_needs_a_ref_and_excludes_changed():
    assert parse_args(["--changed-since"]).exit_code == 1
    assert parse_args(["--changed-since", "main"]).changed_since == "main"
    assert parse_args(["--changed", "--changed-since", "main"]).exit_code == 1
