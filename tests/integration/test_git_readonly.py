"""The guarantee the whole feature rests on (FR-018, SC-003, Principle II).

The constitution says a tool that can alter what it observes is a liability no amount of
usefulness offsets. This is the first feature pointed at the user's real repositories, so
read-only is a test before it is a claim.
"""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path

import pytest

from fixtures import gitrepos
from iknowwhatyoudid.config.model import ConfiguredSource
from iknowwhatyoudid.errors import GitCommandNotAllowedError
from iknowwhatyoudid.git import binary
from iknowwhatyoudid.git.reader import GitReader
from iknowwhatyoudid.records.model import RunMode


def digest(root: Path) -> str:
    """A hash over every file in the repository, contents and paths."""
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        hasher.update(str(path.relative_to(root)).encode("utf-8"))
        try:
            hasher.update(path.read_bytes())
        except OSError:  # pragma: no cover - a lock file may vanish mid-walk
            hasher.update(b"<unreadable>")
    return hasher.hexdigest()


def git_source(name: str, root: Path) -> ConfiguredSource:
    return ConfiguredSource(
        name=name,
        kind="git.local",
        index=0,
        settings={
            "paths": [str(root)],
            "identities": [gitrepos.ME_EMAIL],
        },
    )


@pytest.fixture
def repositories(tmp_path: Path) -> Path:
    root = tmp_path / "dev"
    root.mkdir()
    built = gitrepos.plain(root)
    gitrepos.with_other_authors(root)
    gitrepos.empty(root)
    gitrepos.bare_clone(root, built.path)
    return root


def test_a_full_read_leaves_every_repository_byte_identical(repositories: Path) -> None:
    """SC-003 — including a sweep, which is the mode that could withdraw."""
    before = {
        repo.name: digest(repo) for repo in repositories.iterdir() if repo.is_dir()
    }

    reader = GitReader()
    source = git_source("repos", repositories)
    for mode in (RunMode.INCREMENTAL, RunMode.SWEEP):
        list(reader.read(source, None, None, mode))

    after = {repo.name: digest(repo) for repo in repositories.iterdir() if repo.is_dir()}
    assert after == before, "a repository changed during a read"


def test_reading_creates_no_new_ref(repositories: Path) -> None:
    def refs_of(repo: Path) -> set[str]:
        found = set()
        for base in (repo / ".git" / "refs", repo / "refs"):
            if base.is_dir():
                found |= {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}
        return found

    before = {r.name: refs_of(r) for r in repositories.iterdir() if r.is_dir()}
    list(GitReader().read(git_source("repos", repositories), None, None, RunMode.SWEEP))
    after = {r.name: refs_of(r) for r in repositories.iterdir() if r.is_dir()}

    assert after == before


def test_reading_leaves_the_working_tree_alone(tmp_path: Path) -> None:
    built = gitrepos.plain(tmp_path)
    tracked = {
        p.relative_to(built.path): p.read_bytes()
        for p in built.path.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }

    list(GitReader().read(git_source("r", tmp_path), None, None, RunMode.SWEEP))

    after = {
        p.relative_to(built.path): p.read_bytes()
        for p in built.path.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }
    assert after == tracked


# --- the allow-list is the mechanism, not the intention -----------------------------


@pytest.mark.parametrize(
    "forbidden",
    ["fetch", "gc", "checkout", "commit", "add", "push", "status", "worktree", "config"],
)
def test_a_mutating_command_cannot_be_run(tmp_path: Path, forbidden: str) -> None:
    """Principle II as an allow-list: a future author cannot reach these by accident."""
    built = gitrepos.plain(tmp_path)
    with pytest.raises(GitCommandNotAllowedError):
        binary.run(built.path, forbidden)


def test_status_is_excluded_deliberately() -> None:
    """It was verified not to write in the case tested, and is still not allowed.

    The design does not depend on knowing the conditions under which `status` would
    refresh an index.
    """
    assert "status" not in binary.ALLOWED


def test_the_allow_list_is_only_read_only_commands() -> None:
    assert binary.ALLOWED <= {
        "rev-parse",
        "rev-list",
        "log",
        "for-each-ref",
        "cat-file",
        "reflog",
        "--version",
    }


def test_the_safety_environment_is_applied(tmp_path: Path) -> None:
    """Locks, prompts, hooks and maintenance are all disabled."""
    assert binary._SAFE_ENV["GIT_OPTIONAL_LOCKS"] == "0"
    assert binary._SAFE_ENV["GIT_TERMINAL_PROMPT"] == "0"
    assert "gc.auto=0" in binary._SAFE_CONFIG
    assert "core.hooksPath=" in binary._SAFE_CONFIG


def test_reading_opens_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-019, SC-004 — even with a remote configured.

    Asserts on socket creation rather than on output: a run that tried to fetch would
    fail loudly, but a run that merely opened a socket must fail this test too.
    """
    built = gitrepos.plain(tmp_path)
    gitrepos.add_unreachable_remote(built.path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("reading a repository opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    records = list(
        GitReader().read(git_source("r", tmp_path), None, None, RunMode.SWEEP)
    )
    assert records, "it still read the history"


# --- and nothing is written outside the paths the test named -------------------------


def _fingerprint(path: Path) -> tuple[bool, float | None, int | None]:
    """Whether a path exists, and if so when it last changed and how big it is."""
    try:
        stat = path.stat()
    except OSError:
        return (False, None, None)
    return (True, stat.st_mtime, stat.st_size)


def test_a_run_never_touches_the_real_configuration_or_data_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`0002`'s rule, re-asserted now that a source actually reads.

    Every test passes `--config` and `--store`, but a default resolved in the wrong
    place would silently write to the developer's own store — and a test suite that
    quietly edits the machine it runs on is exactly the failure Principle I forbids.
    Watched paths include the log, which `0001` had to be corrected for once already.
    """
    from iknowwhatyoudid.cli.main import main
    from iknowwhatyoudid.config.location import default_config_path
    from iknowwhatyoudid.store.location import default_log_path, default_store_path

    watched = {
        "config": default_config_path(),
        "config dir": default_config_path().parent,
        "store": default_store_path(),
        "data dir": default_store_path().parent,
        "log": default_log_path(),
    }
    before = {name: _fingerprint(path) for name, path in watched.items()}

    dev = tmp_path / "dev"
    dev.mkdir()
    gitrepos.plain(dev)
    (tmp_path / "config.toml").write_text(
        '[[source]]\nname = "repos"\nkind = "git.local"\n'
        f'paths = ["{dev.as_posix()}"]\nidentities = ["{gitrepos.ME_EMAIL}"]\n',
        encoding="utf-8",
    )
    argv = ["--config", str(tmp_path / "config.toml"), "--store", str(tmp_path / "s.db")]
    # Every command that takes a configuration; `store info` takes none, so it is run
    # with the store override alone.
    for command in (["sources", "validate"], ["ingest"], ["ingest", "--sweep"],
                    ["repos", "list"], ["projects", "list"]):
        main([*command, *argv])
    main(["store", "info", "--store", str(tmp_path / "s.db")])
    capsys.readouterr()

    after = {name: _fingerprint(path) for name, path in watched.items()}
    changed = [name for name in watched if before[name] != after[name]]
    assert not changed, f"the run touched the real {', '.join(changed)}"
    assert (tmp_path / "s.db").exists(), "it did write where it was told to"
