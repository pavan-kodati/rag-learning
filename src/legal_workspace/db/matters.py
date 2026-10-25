"""Matters, parties, aliases and batches."""

from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.errors import UniqueViolation
from rapidfuzz import fuzz

from legal_workspace.db.pool import Conn

from ..domain.normalise import normalise_name
from ..domain.types import PartyRole
from ..errors import BadRequest, Conflict, NotFound, ValidationFailed

Row = dict[str, Any]
_ROLE_WORDS = {
    "plaintiff": PartyRole.PLAINTIFF, "petitioner": PartyRole.PETITIONER, "claimant": PartyRole.PLAINTIFF,
    "defendant": PartyRole.DEFENDANT, "respondent": PartyRole.RESPONDENT,
}  # fmt: skip
MATTER_TYPES = {"BREACH", "PAYMENT_RECOVERY", "TERMINATION_INJUNCTION"}


def create_matter(
    conn: Conn,
    *,
    matter_number: str,
    title: str,
    matter_type: str,
    forum: str | None = None,
    created_by: str | None = None,
    parties: list[dict[str, Any]] | None = None,
) -> Row:
    if not matter_number.strip() or not title.strip():
        raise ValidationFailed("matter_number and title are required")
    if matter_type not in MATTER_TYPES:
        raise ValidationFailed(f"matter_type must be one of {sorted(MATTER_TYPES)}")
    try:
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO matters (matter_number, title, matter_type, current_forum, created_by) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING *",
                (matter_number.strip(), title.strip(), matter_type, forum, created_by),
            ).fetchone()
            assert row is not None
            for p in parties or []:
                add_party(conn, row["matter_id"], p["name"], p.get("role", "OTHER"), p.get("aliases") or [])
    except UniqueViolation as e:
        raise Conflict(f"a matter numbered {matter_number!r} already exists") from e
    return row


def get_matter(conn: Conn, matter_id: str) -> Row:
    try:
        row = conn.execute("SELECT * FROM matters WHERE matter_id = %s", (matter_id,)).fetchone()
    except psycopg.errors.InvalidTextRepresentation as e:  # malformed UUID
        raise NotFound(f"matter {matter_id!r} not found") from e
    if row is None:
        raise NotFound(f"matter {matter_id} not found")
    return row


def list_matters(conn: Conn) -> list[Row]:
    return conn.execute(
        "SELECT m.*, COALESCE((SELECT max(batch_seq) FROM ingestion_batches b WHERE b.matter_id = m.matter_id "
        "AND b.status = 'COMMITTED'), 0) AS latest_batch, "
        "(SELECT count(*) FROM documents d WHERE d.matter_id = m.matter_id) AS document_count "
        "FROM matters m ORDER BY m.created_at DESC"
    ).fetchall()


# ---------------------------------------------------------------------------------------- parties
def add_party(conn: Conn, matter_id: str, name: str, role: str, aliases: list[str]) -> Row:
    name = (name or "").strip()
    if not name:
        raise ValidationFailed("party name is required")
    try:
        PartyRole(role)
    except ValueError as e:
        raise ValidationFailed(f"invalid party role {role!r}") from e
    row = conn.execute(
        "INSERT INTO parties (matter_id, canonical_name, role) VALUES (%s,%s,%s) "
        "ON CONFLICT (matter_id, canonical_name) DO UPDATE SET role = EXCLUDED.role RETURNING *",
        (matter_id, name, role),
    ).fetchone()
    assert row is not None
    for alias in {name, *aliases}:
        norm = normalise_name(alias)
        if norm:
            conn.execute(
                "INSERT INTO party_aliases (matter_id, alias_normalised, party_id) VALUES (%s,%s,%s) "
                "ON CONFLICT (matter_id, alias_normalised) DO NOTHING",
                (matter_id, norm, row["party_id"]),
            )
    return row


def add_aliases(conn: Conn, matter_id: str, party_id: str, aliases: list[str]) -> None:
    for alias in aliases:
        norm = normalise_name(alias)
        if norm:
            conn.execute(
                "INSERT INTO party_aliases (matter_id, alias_normalised, party_id) VALUES (%s,%s,%s) "
                "ON CONFLICT (matter_id, alias_normalised) DO NOTHING",
                (matter_id, norm, party_id),
            )


def list_parties(conn: Conn, matter_id: str) -> list[Row]:
    return conn.execute(
        "SELECT p.*, COALESCE(array_agg(a.alias_normalised) FILTER (WHERE a.alias_normalised IS NOT NULL), '{}') AS aliases "
        "FROM parties p LEFT JOIN party_aliases a USING (party_id) WHERE p.matter_id = %s "
        "GROUP BY p.party_id ORDER BY p.canonical_name",
        (matter_id,),
    ).fetchall()


def resolve_party(conn: Conn, matter_id: str, text: str | None) -> Row | None:
    """Map 'Defendant No. 1', 'Kestrel Limited', 'the Customer' to a party. None when unknown or ambiguous."""
    norm = normalise_name(text or "")
    norm = re.sub(r"^(the|m s)\s+", "", norm)
    if not norm:
        return None
    parties = list_parties(conn, matter_id)
    if not parties:
        return None
    by_alias = {a: p for p in parties for a in p["aliases"]}
    if norm in by_alias:
        return by_alias[norm]
    m = re.fullmatch(r"(plaintiff|petitioner|claimant|defendant|respondent)(?:\s+(?:no\s*)?(\d+))?", norm)
    if m:
        role = _ROLE_WORDS[m.group(1)]
        same = [p for p in parties if p["role"] == role.value]
        if m.group(2):
            idx = int(m.group(2)) - 1
            return same[idx] if 0 <= idx < len(same) else None
        return same[0] if len(same) == 1 else None
    scored = sorted(
        ((fuzz.token_set_ratio(norm, alias), p) for alias, p in by_alias.items()),
        key=lambda t: t[0],
        reverse=True,
    )
    if scored and scored[0][0] >= 90:
        best = scored[0][1]
        if all(p["party_id"] == best["party_id"] for s, p in scored if s >= 90):
            return best
    return None


# ---------------------------------------------------------------------------------------- batches
def open_batch(conn: Conn, matter_id: str, label: str | None = None) -> Row:
    """Open the next batch. Only one batch may be OPEN or PROCESSING at a time."""
    with conn.transaction():
        conn.execute("SELECT 1 FROM matters WHERE matter_id = %s FOR UPDATE", (matter_id,))
        busy = conn.execute(
            "SELECT batch_seq, status FROM ingestion_batches WHERE matter_id = %s AND status IN ('OPEN','PROCESSING')",
            (matter_id,),
        ).fetchone()
        if busy:
            raise Conflict(f"batch {busy['batch_seq']} is still {busy['status']}; commit or finish it first")
        seq = conn.execute(
            "SELECT COALESCE(max(batch_seq), 0) + 1 AS n FROM ingestion_batches WHERE matter_id = %s",
            (matter_id,),
        ).fetchone()
        assert seq is not None
        row = conn.execute(
            "INSERT INTO ingestion_batches (matter_id, batch_seq, label) VALUES (%s,%s,%s) RETURNING *",
            (matter_id, seq["n"], label),
        ).fetchone()
        assert row is not None
        return row


def get_batch(conn: Conn, matter_id: str, batch_seq: int) -> Row:
    row = conn.execute(
        "SELECT * FROM ingestion_batches WHERE matter_id = %s AND batch_seq = %s", (matter_id, batch_seq)
    ).fetchone()
    if row is None:
        raise NotFound(f"batch {batch_seq} not found in matter {matter_id}")
    return row


def list_batches(conn: Conn, matter_id: str) -> list[Row]:
    return conn.execute(
        "SELECT b.*, (SELECT count(*) FROM documents d WHERE d.matter_id = b.matter_id AND d.batch_seq = b.batch_seq) "
        "AS document_count FROM ingestion_batches b WHERE b.matter_id = %s ORDER BY b.batch_seq",
        (matter_id,),
    ).fetchall()


def set_batch_status(conn: Conn, matter_id: str, batch_seq: int, status: str) -> None:
    if status not in {"OPEN", "PROCESSING", "COMMITTED", "FAILED"}:
        raise BadRequest(f"invalid batch status {status!r}")
    conn.execute(
        "UPDATE ingestion_batches SET status = %s, committed_at = CASE WHEN %s = 'COMMITTED' THEN now() END "
        "WHERE matter_id = %s AND batch_seq = %s",
        (status, status, matter_id, batch_seq),
    )


def latest_committed_seq(conn: Conn, matter_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(max(batch_seq), 0) AS n FROM ingestion_batches WHERE matter_id = %s AND status = 'COMMITTED'",
        (matter_id,),
    ).fetchone()
    assert row is not None
    return int(row["n"])
