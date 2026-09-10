"""Builders for fixture git repositories.

Every repository a test reads is built here, in `tmp_path`. The constitution forbids
testing connector logic against the developer's own repositories, and this is the first
feature that could plausibly be pointed at one by accident.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

ME_NAME = "Test Person"
ME_EMAIL = "me@example.com"
OTHER_NAME = "Someone Else"
OTHER_EMAIL = "other@example.com"

#: Kept deterministic so tests can assert on exact instants.
BASE_EPOCH = 1_772_000_000  # 2026-02-25T08:53:20Z

_ENV = {
    **os.environ,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": "",  # replaced per-call below
}


def _run(repo: Path, *args: str, env_extra: dict[str, str] | None = None) -> str:
    env = {**_ENV, "HOME": str(repo.parent), "GIT_CONFIG_GLOBAL": str(repo.parent / ".gitconfig")}
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {result.stderr}")
    return result.stdout


def _init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run(path, "init", "-q", "-b", "main")
    _run(path, "config", "user.name", ME_NAME)
    _run(path, "config", "user.email", ME_EMAIL)
    _run(path, "config", "commit.gpgsign", "false")
    return path


def commit(
    repo: Path,
    subject: str,
    *,
    body: str | None = None,
    offset_seconds: int = 0,
    author_name: str = ME_NAME,
    author_email: str = ME_EMAIL,
    committer_name: str | None = None,
    committer_email: str | None = None,
    tz: str = "+0100",
    filename: str | None = None,
) -> str:
    """Add one commit and return its hash."""
    name = filename or f"{subject.replace(' ', '-')}.txt"
    (repo / name).write_text(f"{repo.name}: {subject}", encoding="utf-8")
    _run(repo, "add", name)

    when = f"{BASE_EPOCH + offset_seconds} {tz}"
    message = subject if body is None else f"{subject}\n\n{body}"
    _run(
        repo,
        "commit",
        "-q",
        "-m",
        message,
        env_extra={
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_AUTHOR_DATE": when,
            "GIT_COMMITTER_NAME": committer_name or ME_NAME,
            "GIT_COMMITTER_EMAIL": committer_email or ME_EMAIL,
            "GIT_COMMITTER_DATE": when,
        },
    )
    return _run(repo, "rev-parse", "HEAD").strip()


@dataclass(frozen=True, slots=True)
class Built:
    """What `plain()` produced, so tests can assert on exact hashes."""

    path: Path
    first: str
    second: str
    on_branch: str
    merge: str


def plain(root: Path, name: str = "plain-repo") -> Built:
    """A repository with two commits, a branch, and a merge.

    The content is seeded with the repository's name so that two fixture repositories
    do not end up with identical commit hashes. They otherwise would: identical content
    at identical timestamps produces identical SHAs, which made two independent
    repositories look like one — a property of the fixture, not of the world.
    """
    repo = _init(root / name)
    (repo / "README.md").write_text("# " + name, encoding="utf-8")
    _run(repo, "add", "README.md")
    first = commit(repo, "first commit", body="A body that must never be stored.")
    _run(repo, "checkout", "-q", "-b", "feature")
    on_branch = commit(repo, "work on feature", offset_seconds=3600)
    _run(repo, "checkout", "-q", "main")
    second = commit(repo, "second commit", offset_seconds=7200)
    _run(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "feature",
        "-m",
        "merge feature",
        env_extra={
            "GIT_AUTHOR_DATE": f"{BASE_EPOCH + 10800} +0100",
            "GIT_COMMITTER_DATE": f"{BASE_EPOCH + 10800} +0100",
        },
    )
    merge = _run(repo, "rev-parse", "HEAD").strip()
    return Built(repo, first, second, on_branch, merge)


def with_other_authors(root: Path, name: str = "shared-repo") -> Path:
    """Commits by the user and by someone else, so identity matching can be tested.

    Three cases, because they are genuinely different:
      * mine — I authored and committed it
      * theirs — someone else authored *and* committed it; not my work
      * applied — they authored it, I committed it; applying a patch is work I did
    """
    repo = _init(root / name)
    commit(repo, "mine one")
    commit(
        repo,
        "theirs one",
        offset_seconds=60,
        author_name=OTHER_NAME,
        author_email=OTHER_EMAIL,
        committer_name=OTHER_NAME,
        committer_email=OTHER_EMAIL,
    )
    commit(
        repo,
        "applied theirs",
        offset_seconds=90,
        author_name=OTHER_NAME,
        author_email=OTHER_EMAIL,
    )
    commit(repo, "mine two", offset_seconds=120)
    return repo


def empty(root: Path, name: str = "empty-repo") -> Path:
    """A repository with no commits — it has no root commit to be identified by."""
    return _init(root / name)


def bare_clone(root: Path, source: Path, name: str = "bare-repo.git") -> Path:
    target = root / name
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(source), str(target)],
        check=True,
        capture_output=True,
    )
    return target


def worktree(root: Path, source: Path, name: str = "linked-worktree") -> Path:
    """A linked worktree: shares the origin's root commit, so shares its identity."""
    target = root / name
    _run(source, "worktree", "add", "-q", "--detach", str(target))
    return target


def nested(root: Path) -> tuple[Path, Path]:
    """A repository inside another repository's working tree."""
    outer = _init(root / "outer")
    commit(outer, "outer commit")
    inner = _init(outer / "vendor" / "inner")
    commit(inner, "inner commit")
    return outer, inner


def not_a_repository(root: Path, name: str = "notarepo") -> Path:
    """A directory with a `.git` folder full of unrelated files.

    The naive "does `.git` exist?" check calls this a repository. Asking git does not.
    """
    path = root / name
    (path / ".git").mkdir(parents=True)
    (path / ".git" / "hello.txt").write_text("not a repository", encoding="utf-8")
    return path


def rewrite_history(repo: Path) -> str:
    """Amend the tip, so the previous commit hash genuinely ceases to exist."""
    _run(
        repo,
        "commit",
        "-q",
        "--amend",
        "-m",
        "amended subject",
        env_extra={
            "GIT_AUTHOR_DATE": f"{BASE_EPOCH + 20000} +0100",
            "GIT_COMMITTER_DATE": f"{BASE_EPOCH + 20000} +0100",
        },
    )
    return _run(repo, "rev-parse", "HEAD").strip()


def drop_reflog(repo: Path) -> None:
    """Delete the reflog, standing in for the 90-day expiry.

    The evidence for a branch creation lives only here, and it is local and expires —
    which is why a sweep must never treat its absence as the branch being deleted.
    """
    logs = repo / ".git" / "logs"
    if logs.exists():
        for entry in sorted(logs.rglob("*"), reverse=True):
            entry.unlink() if entry.is_file() else entry.rmdir()
        logs.rmdir()


def add_unreachable_remote(repo: Path) -> None:
    """A remote that would fail loudly if anything ever tried to reach it."""
    _run(repo, "remote", "add", "origin", "https://127.0.0.1:1/nothing.git")


def many(root: Path, count: int, prefix: str = "repo") -> list[Path]:
    """`count` minimal repositories, for the large-match warning."""
    made: list[Path] = []
    for index in range(count):
        repo = _init(root / f"{prefix}-{index:03d}")
        commit(repo, f"commit {index}")
        made.append(repo)
    return made


def large(root: Path, count: int, name: str = "large-repo") -> Path:
    """A repository with `count` commits, built through `fast-import`.

    Twenty thousand `git commit` invocations take minutes; the same history through
    `fast-import` takes seconds. The result is an ordinary repository — the shortcut is
    in how the fixture is built, never in how the tool reads it.
    """
    repo = _init(root / name)
    lines = ["reset refs/heads/main\n"]
    for index in range(count):
        when = BASE_EPOCH + index * 60
        content = f"line {index}\n"
        lines.append(
            f"commit refs/heads/main\n"
            f"mark :{index + 1}\n"
            f"author {ME_NAME} <{ME_EMAIL}> {when} +0100\n"
            f"committer {ME_NAME} <{ME_EMAIL}> {when} +0100\n"
            f"data {len('commit ' + str(index))}\n"
            f"commit {index}\n"
            f"M 644 inline file.txt\n"
            f"data {len(content)}\n"
            f"{content}"
        )
    _feed(repo, "".join(lines))
    _run(repo, "reset", "-q", "--hard", "refs/heads/main")
    return repo


def _feed(repo: Path, stream: str) -> None:
    env = {**_ENV, "HOME": str(repo.parent), "GIT_CONFIG_GLOBAL": str(repo.parent / ".gitconfig")}
    result = subprocess.run(
        ["git", "fast-import", "--quiet"],
        cwd=repo,
        env=env,
        input=stream.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors='replace')
        raise RuntimeError(f'git fast-import failed in {repo}: {detail}')
