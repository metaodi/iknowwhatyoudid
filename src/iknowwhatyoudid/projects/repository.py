"""Storing projects and repositories (FR-024 to FR-027, FR-035, FR-040)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..records import timestamps
from ..store.connection import writing
from .model import Project, Repository, RepositoryPath, normalise


def _project(row: sqlite3.Row) -> Project:
    return Project(
        id=int(row["id"]),
        name=str(row["name"]),
        normalised_name=str(row["normalised_name"]),
        ad_hoc=bool(row["ad_hoc"]),
        first_seen_utc=int(row["first_seen_utc"]),
    )


def get_project(connection: sqlite3.Connection, name: str) -> Project | None:
    row = connection.execute(
        "SELECT id, name, normalised_name, ad_hoc, first_seen_utc "
        "FROM user_project WHERE normalised_name = ?",
        (normalise(name),),
    ).fetchone()
    return None if row is None else _project(row)


def project_by_id(connection: sqlite3.Connection, project_id: int) -> Project | None:
    row = connection.execute(
        "SELECT id, name, normalised_name, ad_hoc, first_seen_utc "
        "FROM user_project WHERE id = ?",
        (project_id,),
    ).fetchone()
    return None if row is None else _project(row)


def ensure_project(
    connection: sqlite3.Connection,
    name: str,
    *,
    ad_hoc: bool = False,
    now: int | None = None,
) -> Project:
    """Find or create a project.

    Promotion from ad-hoc to declared is one-way: the user declaring a name the tool
    invented is them confirming it, and a confirmation is not something a later
    fall-back should be able to undo.
    """
    at = timestamps.now_micros() if now is None else now
    existing = get_project(connection, name)
    if existing is not None:
        if existing.ad_hoc and not ad_hoc:
            with writing(connection):
                connection.execute(
                    "UPDATE user_project SET ad_hoc = 0, name = ? WHERE id = ?",
                    (name, existing.id),
                )
            found = project_by_id(connection, existing.id)
            assert found is not None
            return found
        return existing

    with writing(connection):
        connection.execute(
            "INSERT INTO user_project (name, normalised_name, ad_hoc, first_seen_utc) "
            "VALUES (?, ?, ?, ?)",
            (name, normalise(name), int(ad_hoc), at),
        )
    created = get_project(connection, name)
    assert created is not None
    return created


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    project: Project
    repositories: int
    activity: int


def list_projects(connection: sqlite3.Connection) -> list[ProjectSummary]:
    """Every project worth showing.

    A **declared** project with no activity is listed — the user said it exists. An
    **ad-hoc** one with no activity is not (FR-040): it existed only because something
    needed attributing, and nothing does any more.
    """
    rows = connection.execute(
        """
        SELECT p.id, p.name, p.normalised_name, p.ad_hoc, p.first_seen_utc,
               count(d.id) AS activity
        FROM user_project p
        LEFT JOIN derived_attribution d ON d.project_id = p.id
        GROUP BY p.id
        ORDER BY p.ad_hoc, p.name
        """
    ).fetchall()

    summaries: list[ProjectSummary] = []
    for row in rows:
        project = _project(row)
        activity = int(row["activity"])
        if project.ad_hoc and activity == 0:
            continue
        repositories = int(
            connection.execute(
                """
                SELECT count(DISTINCT json_extract(r.payload, '$.repository'))
                FROM derived_attribution d
                JOIN raw_record r ON r.id = d.record_id
                WHERE d.project_id = ?
                """,
                (project.id,),
            ).fetchone()[0]
        )
        summaries.append(ProjectSummary(project, repositories, activity))
    return summaries


def prune_empty_ad_hoc(connection: sqlite3.Connection) -> int:
    """Delete ad-hoc projects that hold nothing (FR-040).

    Only ad-hoc ones: a declared project the user emptied is still a project they
    declared, and deleting it would be the tool overruling them.
    """
    with writing(connection):
        cursor = connection.execute(
            "DELETE FROM user_project WHERE ad_hoc = 1 AND id NOT IN "
            "(SELECT DISTINCT project_id FROM derived_attribution)"
        )
        return int(cursor.rowcount)


# --- repositories --------------------------------------------------------------------


def _repository(connection: sqlite3.Connection, row: sqlite3.Row) -> Repository:
    paths = connection.execute(
        "SELECT path, is_bare, is_worktree FROM raw_repository_path "
        "WHERE repository_id = ? ORDER BY path",
        (int(row["id"]),),
    ).fetchall()
    return Repository(
        id=int(row["id"]),
        identity=str(row["identity"]),
        identity_kind=str(row["identity_kind"]),
        name=str(row["name"]),
        paths=tuple(
            RepositoryPath(Path(str(p["path"])), bool(p["is_bare"]), bool(p["is_worktree"]))
            for p in paths
        ),
        first_seen_utc=int(row["first_seen_utc"]),
        last_seen_utc=int(row["last_seen_utc"]),
    )


def record_repository(
    connection: sqlite3.Connection,
    *,
    identity: str,
    identity_kind: str,
    name: str,
    path: Path,
    root_commit: str | None = None,
    is_bare: bool = False,
    is_worktree: bool = False,
    now: int | None = None,
) -> Repository:
    """Upsert a repository and add the path it was seen at.

    One identity, many paths — a repository found twice is one repository (FR-005).
    """
    at = timestamps.now_micros() if now is None else now
    with writing(connection):
        connection.execute(
            "INSERT INTO raw_repository (identity, identity_kind, root_commit, name, "
            "first_seen_utc, last_seen_utc) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(identity) DO UPDATE SET last_seen_utc = excluded.last_seen_utc, "
            "name = excluded.name, root_commit = excluded.root_commit",
            (identity, identity_kind, root_commit, name, at, at),
        )
        row = connection.execute(
            "SELECT id FROM raw_repository WHERE identity = ?", (identity,)
        ).fetchone()
        repository_id = int(row["id"])
        connection.execute(
            "INSERT INTO raw_repository_path (repository_id, path, is_bare, is_worktree, "
            "last_seen_utc) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(repository_id, path) DO UPDATE SET "
            "  last_seen_utc = excluded.last_seen_utc",
            (repository_id, str(path), int(is_bare), int(is_worktree), at),
        )
    found = get_repository(connection, identity)
    assert found is not None
    return found


def get_repository(connection: sqlite3.Connection, identity: str) -> Repository | None:
    row = connection.execute(
        "SELECT id, identity, identity_kind, root_commit, name, first_seen_utc, "
        "last_seen_utc FROM raw_repository WHERE identity = ?",
        (identity,),
    ).fetchone()
    return None if row is None else _repository(connection, row)


def list_repositories(connection: sqlite3.Connection) -> list[Repository]:
    rows = connection.execute(
        "SELECT id, identity, identity_kind, root_commit, name, first_seen_utc, "
        "last_seen_utc FROM raw_repository ORDER BY name"
    ).fetchall()
    return [_repository(connection, row) for row in rows]
