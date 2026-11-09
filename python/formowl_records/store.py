"""Offline PostgreSQL storage and scoped queries for pending-review records.

Connections default to the caller's libpq settings. An explicit psycopg
connection can participate in a caller-owned transaction. Each loader replaces
its input snapshot atomically; queries see the old or the new snapshot.
"""

from __future__ import annotations

from collections import defaultdict
import calendar
from contextlib import contextmanager
from decimal import Decimal
import hashlib
from itertools import chain, groupby, islice
import json
from pathlib import Path
import re
import time
import unicodedata

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from formowl_contract import sha256_json
from .normalize import normalize


PROPERTY_TYPES = {
    "part_number": "identifier", "manufacturer_part_number": "identifier",
    "po_number": "identifier", "po_date": "date", "delivery_date": "date",
    "quantity": "quantity", "origin_country": "country",
    "supplier": "text", "manufacturer": "text",
}
ENTITY_TYPES = {"part_number": "part", "manufacturer_part_number": "part", "po_number": "purchase_order"}

# R1 exporter project_group validates native parent/row/cell hashes, lineage,
# permissions and inline-family before sealing each row into the imported shard.
# Unknown exporter versions deliberately retain runtime per-record admission.
_NATIVE_FAMILY_EXPORTER = "sha256:ea0e949aa285623805c9f6920e9bd7dff15a9e73285d85a6bdff0d4c79e0801e"


def _native_family_receipt(alias=""):
    prefix = alias + "." if alias else ""
    return sql.SQL("""({p}kind='table_row' AND {p}verified_at_export
        AND {p}export_binding->>'exporter_sha256'={exporter}
        AND {p}export_binding->>'shard' ~ '^[0-9a-f]{{2}}$'
        AND {p}export_binding->>'shard_sha256' ~ '^sha256:[0-9a-f]{{64}}$'
        AND {p}native_locator->>'source_family' IN ('mail_inline_table','attachment_table'))""").format(
            p=sql.SQL(prefix), exporter=sql.Literal(_NATIVE_FAMILY_EXPORTER))



def _native_family_scope(families, alias=""):
    if not isinstance(families, (list, tuple)) or any(
            family not in {"mail", "attachment_table", "document_text"} for family in families):
        raise ValueError("invalid native record source families")
    native = ["mail_inline_table" if family == "mail" else family for family in families if family != "document_text"]
    if set(native) == {"mail_inline_table", "attachment_table"}:
        return sql.SQL(""), False
    field = sql.SQL((alias + "." if alias else "") + "native_locator")
    return sql.SQL(" AND NOT (coalesce({},false) AND NOT ({}->>'source_family'=ANY({}::text[])))").format(
        _native_family_receipt(alias), field, sql.Literal(native)), True

_SCHEMA = """
CREATE TABLE IF NOT EXISTS header_signature (
    header_signature_id text PRIMARY KEY, column_names text[] NOT NULL,
    column_mapping jsonb NOT NULL, mapping_status text NOT NULL
);
CREATE TABLE IF NOT EXISTS record (
    record_id text PRIMARY KEY,
    import_key text NOT NULL, kind text NOT NULL CHECK (kind IN ('table_row','pdf_line','passage')),
    source_observation_id text NOT NULL, source_hash text NOT NULL,
    document_id text, mail_message_id text, sent_at text,
    header_signature_id text REFERENCES header_signature, permission_scope text NOT NULL,
    review_status text NOT NULL DEFAULT 'pending_review' CHECK (review_status = 'pending_review'),
    row_role text, native_locator jsonb NOT NULL, sent_at_evidence jsonb NOT NULL
);
ALTER TABLE record ADD COLUMN IF NOT EXISTS source_revision_sha256 text;
ALTER TABLE record ADD COLUMN IF NOT EXISTS export_binding jsonb;
ALTER TABLE record ADD COLUMN IF NOT EXISTS fact_serving_revision_sha256 text;
ALTER TABLE record ADD COLUMN IF NOT EXISTS verified_at_export boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS record_scope_idx ON record(permission_scope);
CREATE INDEX IF NOT EXISTS record_visible_scope_id_idx ON record(permission_scope, record_id)
    WHERE coalesce(row_role,'') NOT IN ('header','header_candidate');
CREATE INDEX IF NOT EXISTS record_native_export_revision_idx ON record(source_revision_sha256,record_id)
    WHERE kind='table_row' AND verified_at_export AND export_binding IS NOT NULL;
CREATE INDEX IF NOT EXISTS record_fact_serving_revision_idx ON record(fact_serving_revision_sha256,record_id)
    WHERE kind IN ('pdf_line','passage') AND verified_at_export AND export_binding IS NOT NULL;
CREATE INDEX IF NOT EXISTS record_unbound_source_idx ON record(record_id)
    WHERE NOT verified_at_export OR export_binding IS NULL OR
          (kind='table_row' AND source_revision_sha256 IS NULL) OR
          (kind IN ('pdf_line','passage') AND fact_serving_revision_sha256 IS NULL);
CREATE INDEX IF NOT EXISTS record_header_scope_id_idx ON record(permission_scope,record_id)
    WHERE coalesce(row_role,'') IN ('header','header_candidate');
CREATE TABLE IF NOT EXISTS record_value (
    record_id text REFERENCES record ON DELETE CASCADE, ordinal integer NOT NULL,
    column_name_raw text, property_id text, raw_value text, norm_value text, value_type text NOT NULL,
    norm_status text NOT NULL, column_text_norm text, unit text,
    date_role text, date_roles text[] NOT NULL, quote text, native_locator jsonb NOT NULL,
    citation_hash text NOT NULL, evidence_spans jsonb NOT NULL,
    PRIMARY KEY (record_id, ordinal)
);
-- Native cells can exceed the btree row limit, so long text uses hash indexes
-- (equality) and a short btree on the property; range filters scan one property.
DROP INDEX IF EXISTS record_value_property_idx;
DROP INDEX IF EXISTS record_value_column_idx;
CREATE INDEX IF NOT EXISTS record_value_property_only_idx ON record_value(property_id);
CREATE INDEX IF NOT EXISTS record_value_date_range_idx ON record_value(property_id, norm_value) INCLUDE (record_id)
    WHERE value_type='date' AND norm_status='ok';
CREATE INDEX IF NOT EXISTS record_value_unresolved_idx ON record_value(property_id, record_id)
    WHERE property_id IS NOT NULL AND norm_status <> 'ok';
CREATE INDEX IF NOT EXISTS record_value_norm_hash_idx ON record_value USING hash (norm_value);
CREATE INDEX IF NOT EXISTS record_value_column_hash_idx ON record_value USING hash (column_name_raw);
CREATE INDEX IF NOT EXISTS record_value_column_text_hash_idx ON record_value USING hash (column_text_norm);
CREATE TABLE IF NOT EXISTS entity (
    entity_id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    entity_type text NOT NULL, norm_key text NOT NULL, UNIQUE(entity_type, norm_key)
);
CREATE TABLE IF NOT EXISTS record_entity (
    record_id text REFERENCES record ON DELETE CASCADE, entity_id bigint REFERENCES entity,
    via_property text NOT NULL, PRIMARY KEY (record_id, entity_id, via_property)
);
ALTER TABLE record ADD COLUMN IF NOT EXISTS export_members jsonb NOT NULL DEFAULT '{}';
ALTER TABLE record_value ADD COLUMN IF NOT EXISTS export_row_id text;
ALTER TABLE record_value ADD COLUMN IF NOT EXISTS context_spans jsonb NOT NULL DEFAULT '[]';
ALTER TABLE record_entity ADD COLUMN IF NOT EXISTS raw_key text;
ALTER TABLE record_entity ADD COLUMN IF NOT EXISTS citation_hash text;
CREATE INDEX IF NOT EXISTS record_entity_entity_idx ON record_entity(entity_id);
CREATE TABLE IF NOT EXISTS record_unresolved_value_summary (
    permission_scope text NOT NULL, serving_revision text NOT NULL, property_id text NOT NULL,
    source_families text[] NOT NULL, source_proven boolean NOT NULL,
    mail_selector text NOT NULL, selector_proven boolean NOT NULL,
    value_count bigint NOT NULL CHECK(value_count > 0),
    PRIMARY KEY(permission_scope,serving_revision,property_id,source_families,source_proven,mail_selector,selector_proven)
);
CREATE TABLE IF NOT EXISTS record_unresolved_value_summary_coverage (
    permission_scope text NOT NULL, serving_revision text NOT NULL, property_id text NOT NULL,
    summary_version integer NOT NULL, complete boolean NOT NULL,
    total_unresolved bigint NOT NULL CHECK(total_unresolved >= 0),
    PRIMARY KEY(permission_scope,serving_revision,property_id)
);
"""


@contextmanager
def _transaction(connection):
    if connection is None:
        with psycopg.connect() as db:
            yield db
    else:
        with connection.transaction():
            yield connection


def create_schema(*, connection=None):
    with _transaction(connection) as db:
        db.execute("SELECT pg_advisory_xact_lock(198281031, 2)")
        db.execute(_SCHEMA)


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected nonempty text")
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("invalid source digest")
    return value


def _value(column, prop, raw, roles, unit, spans):
    if raw is not None and not isinstance(raw, str):
        if type(raw) not in (int, float):
            raise ValueError("invalid raw value")
        raw = str(raw)
    value_type = PROPERTY_TYPES[prop] if prop is not None else "text"
    normalized = normalize(value_type, raw)
    roles = list(dict.fromkeys(roles))
    span = spans[0]
    return dict(column_name_raw=column, property_id=prop, raw_value=raw, norm_value=normalized["norm"],
                value_type=value_type, norm_status=normalized["status"], column_text_norm=normalize("text", raw)["norm"],
                unit=unit or normalized.get("unit"), date_role=roles[0] if len(roles) == 1 else None,
                date_roles=roles, quote=span["quote"], native_locator=span["native_locator"],
                citation_hash=span["observation_hash"], evidence_spans=spans, context_spans=[], export_row_id=None)


def _check_spans(spans, fact):
    for span in spans:
        oid = _text(span["observation_id"])
        if (fact["observation_hashes"].get(oid) != _hash(span["observation_hash"])
                or oid not in fact["source_observation_ids"] or not isinstance(span["native_locator"], dict)):
            raise ValueError("candidate citation mismatch")


def _candidate(row, manifest, import_key):
    if (row["review_status"] != "pending_review" or row["semantic_correctness_verified"] is not False
            or row["artifact_id"] != "formowl_candidate_fact_row_v1"
            or row["mapping_fingerprint"] != manifest["mapping_fingerprint"]
            or row["source_revision_fingerprint"] != manifest["source_revision"]):
        raise ValueError("candidate row binding mismatch")
    values, evidence = [], []
    scope_id = None
    for prop, facts in row["fields"].items():
        if prop not in PROPERTY_TYPES:
            raise ValueError("unknown ontology property")
        for fact in facts:
            scope = fact["permission_scope"]
            if (sha256_json(scope) != row["permission_scope_fingerprint"]
                    or fact["permission_scope_fingerprint"] != row["permission_scope_fingerprint"]
                    or fact["source_revision_fingerprint"] != row["source_revision_fingerprint"]):
                raise ValueError("inconsistent field scope or revision")
            scope_id = _text(scope["scope_id"])
            spans = fact["evidence_spans"]
            if not spans:
                raise ValueError("candidate field missing citation")
            _check_spans(spans, fact)
            value = _value(fact.get("raw_property"), prop, fact["value"],
                           [t["role"] for t in fact.get("times", []) if t.get("role")],
                           fact.get("unit"), spans)
            value["export_row_id"] = row["row_id"]
            time_spans = [s for t in fact.get("times", []) for s in t.get("evidence_spans", [])]
            _check_spans(time_spans, fact)
            value["context_spans"].extend(s for s in time_spans if s not in spans)
            values.append(value)
            evidence.extend(spans)
    if not evidence:
        raise ValueError("candidate row has no evidence")
    primary = evidence[0]
    locator = primary["native_locator"]
    kind = "pdf_line" if any("page" in s["native_locator"] for s in evidence) else "passage"
    outer = row.get("outer_mail_date") or {}
    sent_at = outer.get("value") if outer.get("status") == "verified" else None
    for subject in row.get("subject_identity", {}).get("sources", []):
        if (sha256_json(subject["permission_scope"]) != row["permission_scope_fingerprint"]
                or subject["source_revision_fingerprint"] != row["source_revision_fingerprint"]):
            raise ValueError("subject source binding mismatch")
        _check_spans(subject["evidence_spans"], subject)
        values[0]["context_spans"].extend(subject["evidence_spans"])
    if sent_at:
        values[0]["context_spans"].extend(outer.get("evidence") or [])
    record = dict(record_id=_text(row["row_id"]), import_key=import_key, kind=kind,
                  _item_or_row=normalize("text", row.get("item_or_row"))["norm"],
                  source_revision_sha256=_hash(manifest["source_revision"]), verified_at_export=True,
                  export_binding={"rows_sha256": _hash(manifest["rows_sha256"])},
                  permission_scope_fingerprint=row["permission_scope_fingerprint"],
                  source_observation_id=primary["observation_id"], source_hash=primary["observation_hash"],
                  document_id=locator.get("attachment_id") or locator.get("document_id"),
                  mail_message_id=locator.get("message_id"), sent_at=sent_at, header_signature_id=None,
                  permission_scope=scope_id, row_role=None, native_locator=locator,
                  sent_at_evidence=outer.get("evidence") or [])
    return record, values


def _export_rows(path, import_key):
    manifest = json.loads(path.with_name("manifest.json").read_bytes())
    mapping = json.loads(path.with_name("mapping.snapshot.json").read_bytes())
    if (manifest["artifact_id"] != "formowl_candidate_fact_export_v1"
            or manifest["review_status"] != "pending_review" or manifest["semantic_correctness_verified"] is not False
            or manifest["mapping_fingerprint"] != sha256_json(mapping)
            or not set(mapping["properties"]).issubset(PROPERTY_TYPES)):
        raise ValueError("invalid export manifest or property mapping")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            count += 1
            yield _candidate(json.loads(raw), manifest, import_key)
    if "sha256:" + digest.hexdigest() != manifest["rows_sha256"] or count != manifest["row_count"]:
        raise ValueError("export row count or seal mismatch")


def _retained_fragments(db, replaced_key):
    """Unpack the other exports before a single-export replacement, including cross-export groups."""
    with db.cursor(name="retained_export_records") as cursor:
        cursor.execute("""SELECT to_jsonb(r), jsonb_agg(to_jsonb(v) - 'record_id' - 'ordinal' ORDER BY v.ordinal)
            FROM record r JOIN record_value v USING(record_id)
            WHERE r.kind IN ('pdf_line','passage') GROUP BY r.record_id""")
        for record, values in cursor:
            members = record.pop("export_members")
            record.pop("review_status")
            # Pre-grouping R2 records are singletons.
            if not members:
                members = {record["record_id"]: record}
            by_id = defaultdict(list)
            for value in values:
                row_id = value["export_row_id"] or record["record_id"]
                value["export_row_id"] = row_id
                by_id[row_id].append(value)
            for row_id, member in members.items():
                if member["import_key"] != replaced_key:
                    yield member, by_id[row_id]


def _group_fragments(rows):
    fragments = {}
    parent = {}
    intervals = defaultdict(list)
    pdf_owners = defaultdict(set)

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for record, values in rows:
        row_id = record["record_id"]
        if row_id in fragments:
            raise ValueError("duplicate export row ID")
        fragments[row_id] = record, values
        parent[row_id] = row_id
        for value in values:
            for span, context in chain(((span, False) for span in value["evidence_spans"]),
                                       ((span, True) for span in value["context_spans"])):
                a, b = span.get("start"), span.get("end")
                if a is None and b is None:
                    continue
                if type(a) is not int or type(b) is not int or not 0 <= a <= b:
                    raise ValueError("invalid source span offsets")
                if a < b:
                    space = (record.get("source_revision_sha256"), record["permission_scope"], record.get("permission_scope_fingerprint"),
                             span["observation_id"], span["observation_hash"],
                             tuple(span.get("field_path", ())))
                    if record["kind"] == "pdf_line":
                        if context or "page" not in span["native_locator"]:
                            continue
                        pdf_owners[space, a, b].add(row_id)
                    intervals[space].append((a, b, row_id))

    # A repeated PDF quote is inherited only when distinct named item rows
    # also have disjoint, narrower-owner evidence away from that quote. Exact
    # same-line duplicates remain anchors even if extractors label them differently.
    owner_intervals = defaultdict(set)
    for key, owners in pdf_owners.items():
        for rid in owners:
            owner_intervals[rid].add(key)
    inherited = {}
    for (space, a, b), owners in pdf_owners.items():
        labels = {fragments[rid][0].get("_item_or_row") for rid in owners}
        if len(labels - {None}) < 2:
            continue
        anchors, anchored = [], set()
        for other_space, start, end in set().union(*(owner_intervals[rid] for rid in owners)):
            local_owners = pdf_owners[other_space, start, end]
            if not local_owners < owners or (other_space == space and start < b and a < end):
                continue
            anchored.update(local_owners)
            anchors.extend((other_space, start, end, label) for rid in local_owners
                           if (label := fragments[rid][0].get("_item_or_row")))
        if any(label != other_label and (local_space != other_space or end <= start2 or end2 <= start)
               for i, (local_space, start, end, label) in enumerate(anchors)
               for other_space, start2, end2, other_label in anchors[i + 1:]):
            inherited[space, a, b] = anchored
    for space, spans in intervals.items():
        intervals[space] = [(a, b, rid) for a, b, rid in spans
            if (space, a, b) not in inherited or fragments[rid][0]["kind"] != "pdf_line" or not (
                fragments[rid][0].get("_item_or_row") or rid in inherited[space, a, b])]

    # Export offsets are Python slice endpoints. Sweep the active union of
    # intervals, joining only spans sharing at least one character.
    for spans in intervals.values():
        right = -1
        for start, end, row_id in sorted(spans):
            if start >= right:
                anchor, right = row_id, end
            else:
                parent[root(row_id)] = root(anchor)
                right = max(right, end)

    components = defaultdict(list)
    for row_id in sorted(fragments):
        components[root(row_id)].append(row_id)
    groups = []
    for ids in components.values():
        members = {rid: fragments[rid][0] for rid in ids}
        representative = dict(members[ids[0]], export_members=members)
        verified = all(r.get("verified_at_export") is True for r in members.values())
        representative.update(verified_at_export=verified,
            source_revision_sha256=representative.get("source_revision_sha256") if verified else None,
            export_binding={"rows_sha256": sorted({r["export_binding"]["rows_sha256"] for r in members.values()})}
                if verified else None)
        for name in ("mail_message_id", "sent_at", "document_id"):
            if any(r[name] != representative[name] for r in members.values()):
                representative[name] = None
        if any(r["kind"] == "pdf_line" for r in members.values()):
            representative["kind"] = "pdf_line"
        representative["sent_at_evidence"] = list({
            sha256_json(span): span for r in members.values() for span in r["sent_at_evidence"]
        }.values())
        fields = [field for rid in ids for field in fragments[rid][1]]
        groups.append((representative, fields))
    return groups


_RECORD_COLUMNS = ("record_id import_key kind source_observation_id source_hash document_id mail_message_id sent_at "
                   "header_signature_id permission_scope row_role native_locator sent_at_evidence export_members "
                   "source_revision_sha256 export_binding verified_at_export").split()
_VALUE_COLUMNS = ("record_id ordinal column_name_raw property_id raw_value norm_value value_type norm_status "
                  "column_text_norm unit date_role date_roles quote native_locator citation_hash evidence_spans "
                  "context_spans export_row_id").split()
_JSON_COLUMNS = {"native_locator", "evidence_spans", "context_spans", "sent_at_evidence", "export_members", "export_binding"}


def _copy_rows(db, table, columns, rows):
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)))
    with db.cursor() as cur, cur.copy(statement) as output:
        for row in rows:
            output.write_row([Jsonb(row[k]) if k in _JSON_COLUMNS and row[k] is not None else row[k] for k in columns])


def _write_rows(db, rows):
    counts = {"records": 0, "values": 0}
    while batch := list(islice(rows, 512)):
        _copy_rows(db, "record", _RECORD_COLUMNS, (record for record, _ in batch))
        _copy_rows(db, "record_value", _VALUE_COLUMNS, (
            dict(field, record_id=record["record_id"], ordinal=i)
            for record, fields in batch for i, field in enumerate(fields)))
        counts["records"] += len(batch)
        counts["values"] += sum(len(fields) for _, fields in batch)
    return counts


def _tokens(raw):
    for surface in raw.split():
        folded = normalize("identifier", surface)["norm"]
        for token in (folded or "").split():
            yield token, surface


def _identity_keys(raw):
    norm = normalize("identifier", raw)["norm"]
    if norm is None:
        return
    yield norm, raw
    yield from _tokens(raw)


_MAX_ENTITY_KEY = 64
# PostgreSQL character classes vary by locale; use Python's existing seed rule.
_ENTITY_DIGIT_PATTERN = "[" + "".join(chr(c) for c in range(0x110000) if chr(c).isdigit()) + "]"
_ENTITY_WHITESPACE_PATTERN = "[" + "".join(chr(c) for c in range(0x110000) if chr(c).isspace()) + "]+"


def eligible_entity_projection_key(entity_type, normalized_key):
    """Check an already NFKC/casefold-normalized entity key for display as a code."""
    if (entity_type not in {"part", "purchase_order"} or not isinstance(normalized_key, str)
            or not 4 <= len(normalized_key) <= _MAX_ENTITY_KEY
            or any(c.isspace() for c in normalized_key)):
        return False
    return (bool(re.search("[a-zA-Z]", normalized_key)) and any(c.isdigit() for c in normalized_key)
            or entity_type == "purchase_order" and normalized_key.isascii() and normalized_key.isdecimal())


def _seed_keys(raw):
    # Full normalized cell and first normalized whitespace token only.
    for key, _ in islice(_identity_keys(raw), 2):
        # Identifiers are short codes; a long cell is a description, not an entity key.
        if 4 <= len(key) <= _MAX_ENTITY_KEY and re.search("[a-zA-Z]", key) and any(c.isdigit() for c in key):
            yield key


def _record_links(records, known, entity_ids):
    for record_id, fields in groupby(records, key=lambda r: r[0]):
        owned = set()
        direct = {}
        mentioned = {}
        for _, scope, prop, raw, citations, context in fields:
            if prop in ENTITY_TYPES:
                for key, surface in _identity_keys(raw):
                    if ENTITY_TYPES[prop] not in known[scope].get(key, ()):
                        continue
                    eid = entity_ids[ENTITY_TYPES[prop], key]
                    owned.add(eid)
                    direct.setdefault((eid, prop), (surface, citations[0]["observation_hash"]))
            for span in chain(citations, context):
                for key, surface in _tokens(span.get("quote") or ""):
                    for kind in known[scope].get(key, ()):
                        eid = entity_ids[kind, key]
                        mentioned.setdefault(eid, (surface, span["observation_hash"]))
        for (eid, prop), proof in direct.items():
            yield record_id, eid, prop, *proof
        for eid, proof in mentioned.items():
            if eid not in owned:
                yield record_id, eid, "quote_mention", *proof


def _link_entities(db):
    # Refresh even untouched records: a new (or removed) identifier changes
    # which whole quote tokens are known in its permission scope.
    known = defaultdict(lambda: defaultdict(set))
    with db.cursor(name="record_entity_seeds") as seeds:
        seeds.execute("""SELECT DISTINCT r.permission_scope, v.property_id, v.raw_value
            FROM record_value v JOIN record r USING(record_id) WHERE v.property_id=ANY(%s)
            AND coalesce(row_role,'') NOT IN ('header','header_candidate')""", (list(ENTITY_TYPES),))
        for scope, prop, raw in seeds:
            for key in _seed_keys(raw):
                known[scope][key].add(ENTITY_TYPES[prop])
    keys = {(kind, key) for names in known.values() for key, kinds in names.items() for kind in kinds}
    with db.cursor() as cur:
        cur.executemany("""INSERT INTO entity(entity_type, norm_key) VALUES (%s,%s)
                           ON CONFLICT (entity_type,norm_key) DO NOTHING""", sorted(keys))
    entity_ids = {(kind, key): eid for kind, key, eid in db.execute("SELECT entity_type,norm_key,entity_id FROM entity")}
    db.execute("DELETE FROM record_entity")
    with db.cursor(name="record_link_sources") as records:
        records.execute("""SELECT r.record_id, r.permission_scope, v.property_id, v.raw_value,
            v.evidence_spans, v.context_spans FROM record_value v JOIN record r USING(record_id)
            WHERE coalesce(row_role,'') NOT IN ('header','header_candidate') ORDER BY r.record_id, v.ordinal""")
        links = _record_links(records, known, entity_ids)
        while batch := list(islice(links, 4096)):
            with db.cursor() as cur, cur.copy("""COPY record_entity
                    (record_id,entity_id,via_property,raw_key,citation_hash) FROM STDIN""") as output:
                for link in batch:
                    output.write_row(link)
    db.execute("DELETE FROM entity e WHERE NOT EXISTS (SELECT 1 FROM record_entity re WHERE re.entity_id=e.entity_id)")


def load_candidate_fact_exports(path, *, connection=None):
    """Load an exports directory as a set, or replace one export by its rows.jsonl."""
    path = Path(path)
    if (path / "exports").is_dir():
        path = path / "exports"
    single = path.is_file() or (path / "rows.jsonl").is_file()
    files = ([path if path.is_file() else path / "rows.jsonl"] if single else sorted(path.glob("*/rows.jsonl")))
    if not files or any(p.name != "rows.jsonl" for p in files):
        raise ValueError("expected candidate export rows.jsonl")
    import_keys = ["export:" + p.parent.name for p in files]
    with _transaction(connection) as db:
        db.execute("SELECT pg_advisory_xact_lock(198281031, 2)")
        _invalidate_unresolved_summaries(db)
        retained = _retained_fragments(db, import_keys[0]) if single else ()
        incoming = chain.from_iterable(_export_rows(file, key) for file, key in zip(files, import_keys, strict=True))
        groups = _group_fragments(chain(retained, incoming))
        db.execute("DELETE FROM record WHERE kind IN ('pdf_line','passage')")
        counts = _write_rows(db, iter(groups))
        _link_entities(db)
        rebuild_unresolved_value_summaries(connection=db)
    return counts


def verify_fact_serving_spans(revision, *, connection, audit=None):
    """Bind sealed fact records to a serving pin by checking every cited Observation.

    Run after loading or replacing fact exports. A fresh import has no serving
    receipt. A missing or changed citation clears eligibility for this record.
    """
    from formowl_contract import ContractValidationError
    from collections import Counter
    pin = _hash(revision.safe_binding["source_revision_sha256"])
    reader = revision.source_records
    scopes = set(revision.authorized_source.source_scope_ids)
    observed = {}
    counts = Counter()
    with _transaction(connection) as db:
        db.execute("SELECT pg_advisory_xact_lock(198281031, 2)")
        db.execute("CREATE TEMP TABLE fact_serving_receipts "
                   "(record_id text PRIMARY KEY, serving_pin text) ON COMMIT DROP")
        with db.cursor(name="sealed_fact_spans") as cursor:
            cursor.execute("""SELECT r.record_id,r.kind,r.permission_scope,r.verified_at_export,
                    r.export_binding IS NOT NULL,r.source_revision_sha256,refs.spans
                FROM record r CROSS JOIN LATERAL (
                    SELECT jsonb_agg(DISTINCT jsonb_build_array(s->>'observation_id',s->>'observation_hash')) AS spans
                    FROM record_value v CROSS JOIN LATERAL jsonb_array_elements(v.evidence_spans || v.context_spans) s
                    WHERE v.record_id=r.record_id) refs
                WHERE r.kind IN ('pdf_line','passage')""")
            while records := cursor.fetchmany(512):
                receipts = []
                for rid,kind,scope,verified,sealed,annotation_revision,spans in records:
                    reason = "verified"
                    if scope not in scopes:
                        reason = "outside_scope"
                    elif not verified or not sealed or not spans:
                        reason = "missing_export_binding"
                    else:
                        for oid, key in spans:
                            if oid not in observed:
                                try:
                                    digest = reader.observation_hash(oid)
                                    # A single-scope serving revision already restricts every
                                    # helper to this scope. Multi-scope receipts also bind the
                                    # record to its Observation's source scope.
                                    owner_scope = next(iter(scopes)) if len(scopes)==1 else reader._helper(oid)[0]["source_scope_id"]
                                    observed[oid] = digest, owner_scope
                                except (ContractValidationError, KeyError):
                                    observed[oid] = None
                            if observed[oid] is None:
                                reason = "observation_unavailable"
                            elif observed[oid][1] != scope:
                                reason = "outside_scope"
                            elif observed[oid][0] != key and reason == "verified":
                                reason = "observation_hash_mismatch"
                    counts[reason] += 1
                    if audit is not None:
                        audit(rid,kind,annotation_revision,spans,reason)
                    receipts.append((rid,pin if reason == "verified" else None))
                with db.cursor() as temp, temp.copy("COPY fact_serving_receipts FROM STDIN") as pending:
                    for receipt in receipts:
                        pending.write_row(receipt)
        # Rebinding can also clear receipts outside this revision's scopes.
        # Their previous counters must cease being current before the receipts
        # change; only the newly bound revision is rebuilt below.
        db.execute("""UPDATE record_unresolved_value_summary_coverage c SET complete=false
                      WHERE EXISTS (SELECT 1 FROM record r JOIN fact_serving_receipts f USING(record_id)
                          WHERE r.permission_scope=c.permission_scope
                          AND r.fact_serving_revision_sha256=c.serving_revision
                          AND r.fact_serving_revision_sha256 IS DISTINCT FROM f.serving_pin)""")
        db.execute("""UPDATE record r SET fact_serving_revision_sha256=f.serving_pin
                      FROM fact_serving_receipts f WHERE r.record_id=f.record_id
                      AND r.fact_serving_revision_sha256 IS DISTINCT FROM f.serving_pin""")
        db.execute("DROP TABLE fact_serving_receipts")
        rebuild_unresolved_value_summaries(revision, connection=db)
    return dict(counts)


def _native_input(path, *, with_binding=False):
    """Stream either a legacy JSONL file or the committed, complete R1 snapshot."""
    if path.is_file():
        with path.open("rb") as stream:
            for line in stream:
                row = _json_row(line)
                yield (row, None, None) if with_binding else row
        return
    summary = json.loads((path / "summary.safe.json").read_bytes())
    checkpoint = json.loads((path / "checkpoint.safe.json").read_bytes())
    shards = checkpoint["completed_shards"]
    if (summary.get("status") != "complete" or not summary.get("source_binding_validated")
            or summary.get("artifact_id") != "formowl_native_table_records_v1"
            or checkpoint.get("artifact_id") != summary["artifact_id"]
            or not summary.get("binding") or checkpoint.get("binding") != summary["binding"]
            or not isinstance(shards, dict) or len(shards) != summary.get("total_shards")
            or len(shards) != summary.get("completed_shards")):
        raise ValueError("incomplete or mismatched native snapshot")
    total_rows = total_cells = total_bytes = 0
    for shard, seal in sorted(shards.items()):
        if not re.fullmatch(r"[0-9a-f]{2}", shard):
            raise ValueError("invalid native shard ID")
        revision = summary["binding"].get("source_revision_sha256")
        exporter = summary["binding"].get("exporter_sha256")
        binding = None
        if summary.get("source_binding_validated") is True and revision and exporter:
            revision = _hash(revision)
            binding = {"exporter_sha256": _hash(exporter), "shard": shard, "shard_sha256": _hash(seal["sha256"])}
        digest = hashlib.sha256()
        rows = cells = size = 0
        with (path / f"rows-{shard}.jsonl").open("rb") as stream:
            for line in stream:
                digest.update(line)
                size += len(line)
                row = _json_row(line)
                rows += 1
                cells += len(row["cells"])
                yield (row, revision if binding else None, binding) if with_binding else row
        if (seal["sha256"] != "sha256:" + digest.hexdigest() or seal["row_count"] != rows
                or seal["size_bytes"] != size or seal["cell_count"] != cells):
            raise ValueError("native shard does not match checkpoint")
        total_rows += rows
        total_cells += cells
        total_bytes += size
    if (total_rows, total_cells, total_bytes) != (summary["row_count"], summary["cell_count"], summary["row_output_bytes"]):
        raise ValueError("native snapshot totals do not match")


_NUL_SUBSTITUTE = "\u2400"  # SYMBOL FOR NULL; PostgreSQL text cannot hold U+0000.


def _without_nul(value):
    if isinstance(value, str):
        return value.replace("\x00", _NUL_SUBSTITUTE)
    if isinstance(value, list):
        return [_without_nul(item) for item in value]
    if isinstance(value, dict):
        return {_without_nul(key): _without_nul(item) for key, item in value.items()}
    return value


def _json_row(line):
    """Parse one sealed row; the seal covers the original bytes, display text swaps U+0000."""
    row = json.loads(line)
    if b"\\u0000" not in line:
        return row
    clean = _without_nul(row)
    if clean != row:
        # Hashes and mapping keys stay bound to the original header names.
        clean["_raw_header_signature"] = row.get("header_signature")
        clean["_nul_substituted"] = True
    return clean


def _native_records(db, path, mapping):
    signatures = {}
    for row, revision, binding in _native_input(path, with_binding=True):
        cells = sorted(row["cells"], key=lambda cell: cell["cell_index"])
        indices = [cell["cell_index"] for cell in cells]
        # A source row may carry no cells; keep the row, hash and scope with zero values.
        if len(set(indices)) != len(indices):
            raise ValueError("invalid native cells")
        names = row["header_signature"]
        sid = None
        columns = None
        actual = [cell.get("column_name") for cell in cells]
        if names is not None and (names != actual or any(
                name is not None and (not isinstance(name, str) or not name.strip()) for name in names)):
            raise ValueError("native header signature does not match cells")
        named = sum(name is not None for name in actual)
        raw_names = row.get("_raw_header_signature", names)
        computed = sha256_json(raw_names) if names is not None and named else None
        if (("header_signature_hash" in row and row["header_signature_hash"] != computed)
                or ("named_cell_count" in row and row["named_cell_count"] != named)
                or ("complete" in row and row["complete"] is not (bool(cells) and named == len(cells)))):
            raise ValueError("native header metadata mismatch")
        if computed is not None:
            sid = row.get("header_signature_id") or computed
            if "header_signature_hash" in row and sid != computed:
                raise ValueError("conflicting native signature IDs")
            columns = mapping.get(sid)
            if sid not in signatures:
                if columns is not None and (not isinstance(columns, list) or len(columns) != len(names)
                        or any(name is None and entry is not None for name, entry in zip(names, columns))):
                    raise ValueError("native mapping width mismatch")
                db.execute("INSERT INTO header_signature VALUES (%s,%s,%s,%s)",
                    (sid, names, Jsonb(columns or []), "pending_review" if columns is not None else "unmapped"))
                signatures[sid] = names
            if signatures[sid] != names:
                raise ValueError("conflicting native header names")
        source_id = _text(row["observation_id"])
        locator = {k: row[k] for k in ("table_index", "row_index")}
        if row.get("_nul_substituted"):
            locator["nul_substituted"] = "U+0000 shown as U+2400"
        locator.update({k: row[k] for k in (
            "table_id", "sheet_name", "source_family", "document_id", "attachment_observation_id",
            "attachment_asset_id", "asset_id", "mail_observation_id", "mail_message_id", "mail_message_occurrence_id"
        ) if row.get(k) is not None})
        values = []
        for i, cell in enumerate(cells):
            mapped = columns[i] if columns is not None else None
            prop = mapped.get("property_id") if mapped else None
            role = mapped.get("date_role") if mapped else None
            span = {"observation_hash": _hash(cell["observation_hash"]), "quote": cell["text"],
                    "native_locator": {**locator, "cell_index": cell["cell_index"]}}
            if cell.get("observation_id"):
                span["observation_id"] = cell["observation_id"]
            values.append(_value(cell.get("column_name"), prop, cell["text"], [role] if role else [], None, [span]))
        record = dict(record_id="native:" + source_id, import_key="native", kind="table_row",
                      source_revision_sha256=revision, export_binding=binding, verified_at_export=binding is not None,
                      source_observation_id=source_id, source_hash=_hash(row["observation_hash"]),
                      document_id=row.get("document_id") or row.get("attachment_id"),
                      mail_message_id=row.get("mail_message_id"), sent_at=row.get("sent_at"),
                      header_signature_id=sid, permission_scope=_text(row["permission_scope_id"]),
                      row_role=row.get("row_role"), native_locator=locator, sent_at_evidence=[], export_members={})
        yield record, values


def load_native_rows(path, mapping=None, *, connection=None, revision=None):
    """Replace the native snapshot. Mapping is keyed by signature, then by column position.

    The entries in each ordered mapping are null or {property_id, date_role}.
    Cells without a mapping keep their raw labels and null ontology properties.
    Pass the bound serving revision to preserve fact family proof on replacement.
    Without it, retained facts have explicit unknown family proof until backfill.
    """
    with _transaction(connection) as db:
        db.execute("SELECT pg_advisory_xact_lock(198281031, 2)")
        _invalidate_unresolved_summaries(db)
        db.execute("DELETE FROM record WHERE import_key='native'")
        db.execute("DELETE FROM header_signature")
        counts = _write_rows(db, _native_records(db, Path(path), mapping or {}))
        _link_entities(db)
        rebuild_unresolved_value_summaries(revision, connection=db)
    return counts


def _invalidate_unresolved_summaries(db):
    # Imports replace counts and their coverage in the same writer transaction.
    db.execute("UPDATE record_unresolved_value_summary_coverage SET complete=false")


def _unresolved_source_proof(revision, scope, spans, observed):
    from formowl_contract import ContractValidationError
    from formowl_mail.hybrid import _semantic_observation_retrieval_source_family
    from formowl_mail.issue56_sealed_source import _authorized_mail_selector_for_asset
    families, selectors = set(), set()
    if revision is None or not spans:
        return (), False, "", False
    reader = revision.source_records
    for oid, digest in spans:
        key = oid, digest, scope
        if key not in observed:
            try:
                helper, authority = reader._helper(oid)
                if helper["observation_hash"] != digest or helper["source_scope_id"] != scope:
                    raise ContractValidationError("summary source binding changed")
                family = helper.get("retrieval_source_family")
                if family is None:
                    family = _semantic_observation_retrieval_source_family(reader.get_observation(oid))
                if not isinstance(family, str) or not family:
                    raise ContractValidationError("summary source family unavailable")
                observed[key] = family, _authorized_mail_selector_for_asset(authority.asset)
            except (ContractValidationError, KeyError, AttributeError):
                observed[key] = None
        if observed[key] is None:
            return (), False, "", False
        family, selector = observed[key]
        families.add(family)
        selectors.add(selector)
    common_selector = next(iter(selectors)) if len(selectors) == 1 else None
    return tuple(sorted(families)), True, common_selector or "", True


def rebuild_unresolved_value_summaries(revision=None, *, connection):
    """Atomically replace scoped counters; a supplied sealed revision proves fact families.

    The caller owns the writer connection. No source, annotation or entity is
    modified. Native selector proof is deliberately unavailable. Imports without
    a bound reader publish structural counts with explicit unknown fact families.
    """
    from collections import Counter
    pin = _hash(revision.safe_binding["source_revision_sha256"]) if revision is not None else None
    scopes = list(revision.authorized_source.source_scope_ids) if revision is not None else None
    with _transaction(connection) as db:
        db.execute("SELECT pg_advisory_xact_lock(198281031, 2)")
        condition = sql.SQL("r.verified_at_export AND r.export_binding IS NOT NULL AND ")
        effective_pin = sql.SQL("(CASE WHEN r.kind='table_row' THEN r.source_revision_sha256 ELSE r.fact_serving_revision_sha256 END)")
        condition += effective_pin + sql.SQL(" IS NOT NULL AND coalesce(r.row_role,'') NOT IN ('header','header_candidate')")
        params = [list(PROPERTY_TYPES)]
        if revision is not None:
            condition += sql.SQL(" AND r.permission_scope=ANY(%s) AND {}=%s").format(effective_pin)
            params.extend([scopes, pin])
            pairs = {(scope, pin) for scope in scopes}
        else:
            pairs = set(db.execute(sql.SQL("SELECT DISTINCT r.permission_scope,{} FROM record r WHERE ").format(effective_pin)+condition).fetchall())
            pairs.update(db.execute("SELECT DISTINCT permission_scope,serving_revision FROM record_unresolved_value_summary_coverage").fetchall())
        buckets, totals, observed, proofs = Counter(), Counter(), {}, {}
        query = sql.SQL("""WITH unresolved AS MATERIALIZED (
            SELECT record_id,property_id,count(*) AS n FROM record_value
            WHERE property_id=ANY(%s) AND norm_status<>'ok' GROUP BY record_id,property_id)
            SELECT r.record_id,r.kind,r.permission_scope,{pin},n.proven,r.native_locator->>'source_family',u.property_id,u.n,
                CASE WHEN n.proven THEN NULL ELSE (SELECT jsonb_agg(DISTINCT jsonb_build_array(
                    s->>'observation_id',s->>'observation_hash')) FROM record_value v
                    CROSS JOIN LATERAL jsonb_array_elements(v.evidence_spans || v.context_spans) s
                    WHERE v.record_id=r.record_id) END
            FROM unresolved u JOIN record r USING(record_id)
            CROSS JOIN LATERAL(SELECT coalesce({receipt},false) AS proven) n WHERE {condition}
            ORDER BY r.record_id,u.property_id""").format(pin=effective_pin,receipt=_native_family_receipt("r"),condition=condition)
        with db.cursor(name="unresolved_summary_source_proofs") as cursor:
            cursor.execute(query, params)
            while rows := cursor.fetchmany(512):
                for rid, kind, scope, serving_pin, native, family, prop, count, spans in rows:
                    if native:
                        proof = (("mail" if family == "mail_inline_table" else family,), True, "", False)
                    elif kind == "table_row":
                        # Cell helper presence alone does not prove native row,
                        # parent, same-row cells or selector admission.
                        proof = ((), False, "", False)
                    else:
                        if rid not in proofs:
                            proofs[rid] = _unresolved_source_proof(revision, scope, spans, observed)
                        proof = proofs[rid]
                    families, proven, selector, selector_proven = proof
                    buckets[scope,serving_pin,prop,families,proven,selector,selector_proven] += count
                    totals[scope,serving_pin,prop] += count
        if revision is None:
            db.execute("DELETE FROM record_unresolved_value_summary")
            db.execute("DELETE FROM record_unresolved_value_summary_coverage")
        else:
            for table in ("record_unresolved_value_summary", "record_unresolved_value_summary_coverage"):
                db.execute(sql.SQL("DELETE FROM {} WHERE permission_scope=ANY(%s) AND serving_revision=%s").format(sql.Identifier(table)), (scopes,pin))
        with db.cursor() as cursor:
            cursor.executemany("INSERT INTO record_unresolved_value_summary VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                [(*key[:3],list(key[3]),*key[4:],count) for key,count in sorted(buckets.items())])
            cursor.executemany("INSERT INTO record_unresolved_value_summary_coverage VALUES (%s,%s,%s,1,true,%s)",
                [(scope,serving_pin,prop,totals[scope,serving_pin,prop])
                 for scope,serving_pin in sorted(pairs) for prop in PROPERTY_TYPES])
    return {"status":"complete", "bucket_count":len(buckets), "coverage_count":len(pairs)*len(PROPERTY_TYPES),
            "unresolved_value_count":sum(buckets.values()),
            "unproven_source_value_count":sum(count for key,count in buckets.items() if not key[4]),
            "unproven_selector_value_count":sum(count for key,count in buckets.items() if not key[6])}


def _unresolved_summary_count(db, scopes, pin, properties, *, families, selector, restricted, unsupported, required):
    def unavailable(reason):
        return {"unresolved_value_count_status":"unavailable", "unresolved_value_count_reason":reason}
    if pin is None:
        return unavailable("serving_revision_required") if required else None
    try:
        with db.transaction():
            coverage = db.execute("""SELECT permission_scope,property_id,total_unresolved,complete,summary_version
                FROM record_unresolved_value_summary_coverage WHERE permission_scope=ANY(%s)
                AND serving_revision=%s AND property_id=ANY(%s)""", (scopes,pin,properties)).fetchall()
            if not coverage and not required:
                return None  # Legacy diagnostic callers; product always requires the summary.
            expected = {(scope,prop) for scope in scopes for prop in properties}
            if {(scope,prop) for scope,prop,_,_,_ in coverage} != expected:
                return unavailable("scope_not_covered")
            if any(not complete or version != 1 for _,_,_,complete,version in coverage):
                return unavailable("summary_not_current")
            if unsupported:
                return unavailable("unsupported_filters")
            if restricted and families is None:
                return unavailable("source_scope_unproven")
            rows = db.execute("""SELECT permission_scope,property_id,source_families,source_proven,
                mail_selector,selector_proven,value_count FROM record_unresolved_value_summary
                WHERE permission_scope=ANY(%s) AND serving_revision=%s AND property_id=ANY(%s)""",
                (scopes,pin,properties)).fetchall()
    except (psycopg.errors.UndefinedTable, psycopg.errors.InsufficientPrivilege):
        return unavailable("summary_unavailable") if required else None
    from collections import Counter
    actual = Counter()
    for scope,prop,_,_,_,_,count in rows:
        actual[scope,prop] += count
    if any(actual[scope,prop] != total for scope,prop,total,_,_ in coverage):
        return unavailable("summary_integrity_failure")
    total = 0
    for _,_,record_families,proven,owner,selector_proven,count in rows:
        if families is not None:
            if not proven:
                return unavailable("source_scope_unproven")
            if not set(record_families).issubset(families):
                continue
        if selector is not None:
            if not selector_proven:
                return unavailable("selector_unproven")
            if owner != selector:
                continue
        total += count
    return {"unresolved_value_count_status":"available", "unresolved_value_count":total}


def _column(prop):
    if not isinstance(prop, str):
        raise ValueError("invalid property")
    if prop.startswith("column:"):
        return _text(prop.removeprefix("column:"))
    if prop not in PROPERTY_TYPES:
        raise ValueError("unknown ontology property")
    return None


def field_name_key(label):
    """One comparison key for ontology labels and literal source columns."""
    return "".join(unicodedata.normalize("NFKC", label).casefold().split())


def resolve_raw_columns(labels, permission_scopes, *, source_revision_sha256, connection,
                        _admit=None, _native_source_families=None, _deadline=None, _fact_columns=None,
                        _query_filters=()):
    """Resolve against all pinned authorized names, preserving exact source spelling.

    The bounded model catalog is never the authority for literal columns.
    Equivalent spellings remain a set; no source spelling is chosen or dropped.
    Bound exports may supply their complete private raw-name vocabulary.
    """
    labels = list(dict.fromkeys(_text(label) for label in labels))
    if not labels:
        return {}
    scopes = [_text(scope) for scope in permission_scopes]
    pin = _hash(source_revision_sha256)
    def remaining():
        if _deadline is not None:
            ms = int(1000 * (_deadline - time.monotonic()))
            if ms <= 0:
                raise TimeoutError("record column resolution deadline")
            connection.execute("SELECT set_config('statement_timeout',%s,true)", (str(ms),))
    qualified_native = _native_source_families is not None
    native_scope = _native_family_scope(_native_source_families, "r")[0] if qualified_native else sql.SQL("")
    visible = sql.SQL("""WITH visible AS NOT MATERIALIZED (
        SELECT r.* FROM record r WHERE r.permission_scope=ANY(%s)
        AND coalesce(r.row_role,'') NOT IN ('header','header_candidate')
        AND r.verified_at_export AND r.export_binding IS NOT NULL
        AND (CASE WHEN r.kind='table_row' THEN r.source_revision_sha256 ELSE r.fact_serving_revision_sha256 END)=%s
        """) + native_scope + sql.SQL(") ")
    remaining()
    # Native import validates column_names against every cell, so the existing
    # signature table is the complete native name dictionary. Facts and legacy
    # rows without a signature retain per-record indexed value lookup. OFFSET
    # prevents flattening that small exception path into a full value scan.
    # No dictionary name is accepted or exposed before scoped admission below.
    full_legacy_checked = True
    if _fact_columns is None:
        names = connection.execute(visible + sql.SQL("""SELECT DISTINCT name FROM (
            SELECT unnest(column_names) AS name FROM header_signature
            UNION ALL
            SELECT cols.column_name_raw FROM visible r CROSS JOIN LATERAL (
                SELECT v.column_name_raw FROM record_value v WHERE v.record_id=r.record_id
                AND v.column_name_raw IS NOT NULL OFFSET 0) cols
            WHERE r.header_signature_id IS NULL) dictionary WHERE name IS NOT NULL"""), (scopes,pin)).fetchall()
    else:
        names = connection.execute("SELECT DISTINCT unnest(column_names) FROM header_signature").fetchall()
        names.extend((name,) for name in _fact_columns)
        # A name missing from the native dictionary may belong to an older
        # eligible named row imported without its header signature. An indexed
        # equality predicate provides a superset of every possible final match;
        # no name outside it can add a matching row or projected value.
        seed = None
        for item in sorted(_query_filters, key=lambda item: _column(item["property"]) is not None):
            if item.get("op") not in ("eq", "in"):
                continue
            if _column(item["property"]) is None:
                seed = _filter_ids(item)
            else:
                values = [normalize("text", str(value))["norm"] for value in item["values"]]
                seed = sql.SQL("SELECT record_id FROM record_value WHERE column_text_norm=ANY(%s)"), [values]
            break

        def legacy_names(seed):
            remaining()
            legacy = sql.SQL("""r.kind='table_row' AND r.source_revision_sha256=%s
                AND r.verified_at_export AND r.export_binding IS NOT NULL
                AND r.permission_scope=ANY(%s) AND coalesce(r.row_role,'') NOT IN ('header','header_candidate')
                AND r.header_signature_id IS NULL AND NOT coalesce({},false)""").format(_native_family_receipt("r"))
            args = [pin,scopes]
            if seed is None:
                selected = sql.SQL("SELECT r.record_id FROM record r WHERE ")+legacy
                prefix = sql.SQL("WITH legacy AS MATERIALIZED (")+selected+sql.SQL(") ")
            else:
                seed_query, seed_args = seed
                prefix = visible + sql.SQL(", seed AS MATERIALIZED (SELECT DISTINCT record_id FROM (")
                prefix += seed_query + sql.SQL(") candidates), legacy AS MATERIALIZED (SELECT r.record_id FROM seed s CROSS JOIN LATERAL (")
                prefix += sql.SQL("SELECT r.record_id FROM record r WHERE r.record_id=s.record_id AND ")+legacy
                prefix += sql.SQL(" OFFSET 0) r) ")
                args = [scopes,pin,*seed_args,*args]
            return connection.execute(prefix + sql.SQL("""SELECT DISTINCT v.column_name_raw FROM legacy
                CROSS JOIN LATERAL (SELECT column_name_raw FROM record_value v WHERE v.record_id=legacy.record_id
                    AND v.column_name_raw IS NOT NULL OFFSET 0) v"""), args).fetchall()

        names.extend(legacy_names(seed))
        full_legacy_checked = seed is None
        # A selective empty match is not proof that an explicit field is unknown.
        # Only this uncommon validation case needs the complete older-row path.
        known = {field_name_key(name) for name, in names if isinstance(name,str)}
        if seed is not None and any(field_name_key(label) not in known for label in labels):
            names.extend(legacy_names(None))
            full_legacy_checked = True
    keys = {field_name_key(label) for label in labels}
    candidates = {name for name, in names if isinstance(name, str) and field_name_key(name) in keys}
    admitted = set()
    for name in sorted(candidates):
        remaining()
        native_guard = (sql.SQL(" AND ")+_native_family_receipt("r")
                        if qualified_native and _admit is not None else sql.SQL(""))
        exists = connection.execute(visible + sql.SQL("""SELECT EXISTS(SELECT FROM record_value v
            JOIN visible r USING(record_id) WHERE v.column_name_raw=%s""") + native_guard + sql.SQL(" LIMIT 1)"),
            (scopes,pin,name)).fetchone()[0]
        if exists and (_admit is None or qualified_native):
            admitted.add(name)
            continue
        if _admit is not None:
            remaining()
            prefix = visible + sql.SQL(""", matched AS MATERIALIZED (
                SELECT DISTINCT v.record_id FROM record_value v JOIN visible USING(record_id)
                WHERE v.column_name_raw=%s)""")
            args = [scopes,pin,name]
            rejected = _scope_exclusions(connection, prefix, args, _admit, qualified_native=qualified_native)
            remaining()
            if connection.execute(prefix + sql.SQL("SELECT EXISTS(SELECT FROM matched WHERE record_id<>ALL(%s) LIMIT 1)"),
                                  [*args,rejected]).fetchone()[0]:
                admitted.add(name)
    candidates = admitted
    by_key = defaultdict(set)
    for name in candidates:
        by_key[field_name_key(name)].add(name)
    resolved = {}
    for label in labels:
        matches = by_key[field_name_key(label)]
        if not matches:
            if not full_legacy_checked:
                return resolve_raw_columns(labels, scopes, source_revision_sha256=pin, connection=connection,
                    _admit=_admit, _native_source_families=_native_source_families, _deadline=_deadline,
                    _fact_columns=_fact_columns)
            raise ValueError("unavailable raw column")
        resolved[label] = sorted(matches)
    return resolved


def _column_names(prop, variants):
    column = _column(prop)
    return variants.get(prop, [column]) if column is not None else []


def range_bounds(filters):
    """Keep bounds on the same property together so one value must satisfy all of them."""
    bounds = defaultdict(list)
    for item in filters:
        if item.get("op") not in ("gte", "lte"):
            continue
        prop = item.get("property")
        if not isinstance(prop, str) or PROPERTY_TYPES.get(prop) not in ("date", "quantity"):
            raise ValueError("record range requires a date or quantity property")
        values = item.get("values")
        if (set(item) != {"property", "op", "values"} or not isinstance(values, list) or len(values) != 1
                or type(values[0]) not in (int, float, str)):
            raise ValueError("invalid record range bound")
        result = normalize(PROPERTY_TYPES[prop], str(values[0]))
        if result["status"] != "ok":
            raise ValueError("invalid record range bound")
        bounds[prop].append((item["op"], result["norm"]))
    return bounds


def matches_range(prop, raw, bounds):
    kind = PROPERTY_TYPES[prop]
    value = normalize(kind, raw)
    if value["status"] != "ok":
        return False
    typed = Decimal if kind == "quantity" else str
    current = typed(value["norm"])
    return all(current >= typed(bound) if op == "gte" else current <= typed(bound) for op, bound in bounds)


def _range_ids(prop, bounds):
    params = [prop]
    checks = [sql.SQL("v.value_type='date'")] if PROPERTY_TYPES[prop] == "date" else []
    for op, bound in bounds:
        operator = sql.SQL(">=" if op == "gte" else "<=")
        if PROPERTY_TYPES[prop] == "quantity":
            # CASE protects the numeric cast even if the planner reorders predicates.
            expr = sql.SQL("(CASE WHEN v.property_id='quantity' AND v.norm_status='ok' THEN v.norm_value::numeric END)")
            params.append(Decimal(bound))
        else:
            expr = sql.SQL("v.norm_value")
            params.append(bound)
        checks.append(sql.SQL("{} {} %s").format(expr, operator))
    return (sql.SQL("SELECT v.record_id FROM record_value v WHERE v.property_id=%s AND v.norm_status='ok' AND ") + sql.SQL(" AND ").join(checks), params)


def _iso_month_bounds(fragment):
    match = re.fullmatch(r"([0-9]{4})-(0[1-9]|1[0-2])", fragment)
    if match is None or int(match[1]) < 1:
        return None
    year, month = int(match[1]), int(match[2])
    return [("gte", f"{year:04d}-{month:02d}-01"),
            ("lte", f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}")]


def _filter_ids(item, column_variants=None):
    """Select direct matches and scoped seeds for the same typed entity."""
    if set(item) != {"property", "op", "values"}:
        raise ValueError("invalid filter")
    prop, op, values = item["property"], item["op"], item["values"]
    column = _column(prop)
    if op not in ("eq", "contains", "in") or not isinstance(values, list) or not values:
        raise ValueError("invalid filter operator or values")
    if op != "in" and len(values) != 1:
        raise ValueError("eq and contains require one value")
    kind = "text" if column is not None or (op == "contains" and PROPERTY_TYPES.get(prop) == "date") else PROPERTY_TYPES[prop]
    norms = []
    for raw in values:
        if type(raw) not in (int, float, str):
            raise ValueError("invalid filter value")
        norm = normalize(kind, str(raw))["norm"]
        if norm is None:
            raise ValueError("unresolved filter value")
        norms.append(norm)
    if op == "contains" and column is None and PROPERTY_TYPES[prop] == "date":
        month_bounds = _iso_month_bounds(norms[0])
        if month_bounds is not None:
            # A valid YYYY-MM can occur only as the prefix of normalized ISO
            # dates, so closed calendar bounds are exactly equivalent.
            return _range_ids(prop, month_bounds)
    label, field = ("column_name_raw", "column_text_norm") if column is not None else ("property_id", "norm_value")
    condition = sql.SQL("strpos(v.{}, %s) > 0" if op == "contains" else "v.{} = ANY(%s)").format(sql.Identifier(field))
    comparison = sql.SQL(" = ANY(%s)" if column is not None else " = %s")
    direct = sql.SQL("SELECT v.record_id FROM record_value v WHERE v.{}").format(sql.Identifier(label)) + comparison + sql.SQL(" AND ") + condition
    params = [_column_names(prop, column_variants or {}) if column is not None else prop,
              norms[0] if op == "contains" else norms]
    if prop not in ENTITY_TYPES:
        return direct, params
    key_test = sql.SQL("strpos(e.norm_key, %s)>0" if op == "contains" else "e.norm_key=ANY(%s)")
    # A key must be seeded by the requested property in an authorized record.
    # Only propagate the matching entity, not every other identifier on that record.
    return sql.SQL("""{} UNION
        SELECT re.record_id FROM entity e JOIN record_entity re USING(entity_id)
        WHERE e.entity_type=%s AND {} AND EXISTS (
            SELECT 1 FROM record_entity seed JOIN visible USING(record_id)
            WHERE seed.entity_id=e.entity_id AND seed.via_property=%s)""").format(
                direct, key_test), [*params, ENTITY_TYPES[prop], params[-1], prop]



def known_entity_filters(required_terms, permission_scopes, *, source_revision_sha256, connection,
                         _admit=None, _native_source_families=None, _term_identity_hints=None):
    """Resolve exact typed keys from scoped, pinned direct seeds, without inference.

    Whole terms and their eligible whitespace tokens are exact candidates only.
    Same-kind keys on different terms remain independent AND predicates. A key
    that is both a part and a purchase order is deliberately not auto planned.
    The final execute call still applies source-family/selector admission.
    """
    scopes = [_text(scope) for scope in permission_scopes]
    pin = _hash(source_revision_sha256)
    whole_terms = [norm for term in required_terms if (norm := normalize("identifier", term)["norm"]) is not None]
    tokens_by_term = {term: [token for token in term.split()
        if len(token) >= 4 and any(char.isdigit() for char in token)] for term in whole_terms}
    terms = list(dict.fromkeys(chain(whole_terms, chain.from_iterable(tokens_by_term.values()))))
    if not terms or not scopes:
        return [], False
    qualified_native = _native_source_families is not None
    native_scope = _native_family_scope(_native_source_families, "r")[0] if qualified_native else sql.SQL("")
    matches = connection.execute(sql.SQL("""SELECT DISTINCT seeds.norm_key, seeds.entity_type, seeds.via_property, r.record_id
        FROM (
            SELECT e.norm_key,e.entity_type,re.via_property,re.record_id
            FROM entity e JOIN record_entity re USING(entity_id) WHERE e.norm_key=ANY(%s)
              AND ((e.entity_type='part' AND re.via_property IN ('part_number','manufacturer_part_number'))
                   OR (e.entity_type='purchase_order' AND re.via_property='po_number'))
            UNION
            SELECT v.norm_value, CASE WHEN v.property_id='po_number' THEN 'purchase_order' ELSE 'part' END,
                   v.property_id,v.record_id
            FROM record_value v WHERE v.norm_value=ANY(%s) AND v.norm_status='ok'
              AND v.property_id IN ('part_number','manufacturer_part_number','po_number')
        ) seeds JOIN record r USING(record_id)
        WHERE r.permission_scope=ANY(%s)
          AND coalesce(r.row_role,'') NOT IN ('header','header_candidate')
          AND r.verified_at_export AND r.export_binding IS NOT NULL
          AND (CASE WHEN r.kind='table_row' THEN r.source_revision_sha256 ELSE r.fact_serving_revision_sha256 END)=%s
        """) + native_scope + sql.SQL(" ORDER BY seeds.norm_key,seeds.entity_type,seeds.via_property,r.record_id"),
        (terms, terms, scopes, pin)).fetchall()
    if _admit is not None and matches:
        ids = list({row[3] for row in matches})
        prefix = sql.SQL("WITH matched AS MATERIALIZED (SELECT record_id FROM record WHERE record_id=ANY(%s))")
        rejected = set(_scope_exclusions(connection, prefix, [ids], _admit, qualified_native=qualified_native))
        matches = [row for row in matches if row[3] not in rejected]
    by_key = defaultdict(lambda: defaultdict(set))
    for key, kind, prop, _ in matches:
        by_key[key][kind].add(prop)
    if any(len(by_key[key]) > 1 for key in whole_terms):
        return [], True
    # An admitted whole-term match keeps the original exact-match behavior.
    # Its component tokens neither add filters nor contribute label hints.
    unmatched = [term for term in whole_terms if not by_key.get(term)]
    hints_by_key = defaultdict(set)
    for term in unmatched:
        if (prop := (_term_identity_hints or {}).get(term)) is not None:
            token = term.rsplit(None, 1)[-1]
            if token in tokens_by_term[term]:
                hints_by_key[token].add(prop)
    active = dict.fromkeys(chain(whole_terms, chain.from_iterable(tokens_by_term[term] for term in unmatched)))
    filters = []
    for key in active:
        kinds = by_key[key]
        # Only expanded token candidates can be narrowed by a resolved label.
        # Whole-term ambiguity remains authoritative, even when also hinted.
        hints = hints_by_key[key] if key not in whole_terms else ()
        if hints and kinds:
            if len(hints) != 1:
                return [], True
            prop = next(iter(hints))
            kind = ENTITY_TYPES[prop]
            kinds = {kind: {prop}} if prop in kinds.get(kind, ()) else {}
        if len(kinds) > 1:
            return [], True
        if kinds:
            props = next(iter(kinds.values()))
            prop = "part_number" if "part_number" in props else sorted(props)[0]
            filters.append({"property": prop, "op": "eq", "values": [key]})
    return filters, False


def _scope_exclusions(db, prefix, args, admit, *, qualified_native=False):
    """Stream only identity/hash membership proofs. Full values stay on the server."""
    query = prefix + sql.SQL("""
        SELECT r.record_id,r.kind,r.permission_scope,r.source_observation_id,r.source_hash,spans.refs
        FROM matched JOIN record r USING(record_id)
        CROSS JOIN LATERAL (SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_array(
            s->>'observation_id',s->>'observation_hash')),'[]'::jsonb) AS refs
            FROM record_value v CROSS JOIN LATERAL jsonb_array_elements(v.evidence_spans || v.context_spans) s
            WHERE v.record_id=r.record_id) spans""")
    if qualified_native:
        # visible already rejects qualified families outside the request. Skip
        # hydration only for each individually pinned, sealed admitted row.
        query += sql.SQL(" WHERE NOT coalesce({},false)").format(_native_family_receipt("r"))
    rejected = []
    with db.cursor(name="record_table_scope_proofs") as cur:
        cur.execute(query,args)
        while batch := cur.fetchmany(64):
            for rid,kind,scope,oid,digest,refs in batch:
                evidence = [{"observation_id": key, "observation_hash": val} for key,val in refs]
                record = {"record_id":rid, "kind":kind, "permission_scope":scope,
                          "source_observation_id":oid, "source_hash":digest,
                          "values":[{"evidence_spans":evidence, "context_spans":[]}]}
                if not admit(record):
                    rejected.append(rid)
    return rejected


def _record_result_groups(columns, filters, bounds, column_variants=None):
    """Compute distinct material memberships, original surfaces and counts in PostgreSQL."""
    requested = [
        (i, prop, _column(prop), ENTITY_TYPES.get(prop), bool(
            ENTITY_TYPES.get(prop) != "part" and any(ENTITY_TYPES.get(col) == "part" for col in columns)
            and any(f["property"] == prop and f["op"] == "eq" for f in filters)))
        for i, prop in enumerate(columns)
    ]
    checks = []
    args = [list(values) for values in zip(*requested)]
    args.append(Jsonb({prop: _column_names(prop, column_variants or {}) for prop in columns if _column(prop) is not None}))
    for prop, limits in bounds.items():
        if prop not in columns:
            continue
        expr = (sql.SQL("CASE WHEN v.property_id='quantity' AND v.norm_status='ok' THEN v.norm_value::numeric END")
                if PROPERTY_TYPES[prop] == "quantity" else sql.SQL("v.norm_value"))
        tests = [sql.SQL("v.norm_status='ok'")]
        args.append(prop)
        for op, bound in limits:
            tests.append(expr + sql.SQL(" >= %s" if op == "gte" else " <= %s"))
            args.append(Decimal(bound) if PROPERTY_TYPES[prop] == "quantity" else bound)
        checks.append(sql.SQL(" AND (q.label<>%s OR (") + sql.SQL(" AND ").join(tests) + sql.SQL("))"))
    args.extend([_ENTITY_DIGIT_PATTERN, _ENTITY_WHITESPACE_PATTERN, _ENTITY_WHITESPACE_PATTERN])
    group_query = sql.SQL("""
        , requested(i,label,col,kind,constant_filter) AS (
            SELECT * FROM unnest(%s::int[],%s::text[],%s::text[],%s::text[],%s::bool[])),
        ordered AS MATERIALIZED (SELECT record_id,
            row_number() OVER (ORDER BY hits DESC,newest DESC NULLS LAST,record_id) AS position FROM ranked),
        cells AS MATERIALIZED (
            SELECT o.record_id, q.i, q.kind, v.raw_value AS raw, v.column_name_raw AS name,
                CASE WHEN v.norm_status='ok' THEN v.norm_value END AS norm
            FROM ordered o JOIN record_value v USING(record_id) JOIN requested q ON
              ((q.col IS NULL AND v.property_id=q.label) OR v.column_name_raw=ANY(
                  ARRAY(SELECT jsonb_array_elements_text(%s::jsonb -> q.label)))) WHERE true
        """) + sql.SQL("").join(checks) + sql.SQL("""
        ), needs_link AS MATERIALIZED (
            SELECT o.record_id,q.i,q.kind,q.label FROM ordered o CROSS JOIN requested q WHERE q.kind IS NOT NULL),
        edge_candidates AS MATERIALIZED (
            SELECT n.*, re.raw_key AS raw,e.norm_key AS norm,re.via_property,re.citation_hash,
                bool_or(re.via_property=n.label) OVER (PARTITION BY n.record_id,n.i) AS has_own
            FROM needs_link n JOIN record_entity re USING(record_id)
            JOIN entity e ON e.entity_id=re.entity_id AND e.entity_type=n.kind
            WHERE char_length(e.norm_key) BETWEEN 4 AND 64
              AND strpos(e.norm_key,' ')=0
              AND ((e.norm_key ~ '[a-zA-Z]' AND e.norm_key ~ %s)
                   OR (n.kind='purchase_order' AND e.norm_key ~ '^[0-9]+$'))
              AND (re.via_property='quote_mention'
                   OR (n.kind='part' AND re.via_property IN ('part_number','manufacturer_part_number'))
                   OR (n.kind='purchase_order' AND re.via_property='po_number'))),
        edges AS MATERIALIZED (
            SELECT DISTINCT ON (record_id,i,norm) * FROM edge_candidates
            WHERE NOT has_own OR via_property=label
            ORDER BY record_id,i,norm,(via_property='quote_mention'),via_property),
        edge_cells AS MATERIALIZED (
            SELECT e.record_id,e.i,e.kind,e.raw,p.name,e.norm,
                CASE WHEN e.via_property='quote_mention' THEN 'quote_mention' ELSE 'value' END AS link,
                p.present IS TRUE AS proved
            FROM edges e LEFT JOIN LATERAL (
                SELECT v.column_name_raw AS name,true AS present FROM record_value v
                WHERE v.record_id=e.record_id AND e.via_property=v.property_id
                    AND v.citation_hash=e.citation_hash
                    AND (e.raw=v.raw_value OR e.raw=ANY(regexp_split_to_array(v.raw_value,%s)))
                UNION ALL
                SELECT CASE WHEN ref.context THEN NULL ELSE v.column_name_raw END AS name,true AS present
                FROM record_value v CROSS JOIN LATERAL (
                    SELECT s.span,false AS context FROM jsonb_array_elements(v.evidence_spans) s(span)
                    UNION ALL SELECT s.span,true FROM jsonb_array_elements(v.context_spans) s(span)
                ) ref WHERE v.record_id=e.record_id AND e.via_property='quote_mention'
                    AND ref.span->>'observation_hash'=e.citation_hash
                    AND e.raw=ANY(regexp_split_to_array(ref.span->>'quote',%s))
                LIMIT 1) p ON true),
        projected AS MATERIALIZED (
            SELECT c.*,NULL::text AS link,true AS proved FROM cells c WHERE c.kind IS NULL
            UNION ALL SELECT * FROM edge_cells
            UNION ALL SELECT n.record_id,n.i,n.kind,NULL,NULL,NULL,'unlinked_part',true FROM needs_link n
                WHERE n.kind='part' AND NOT EXISTS (SELECT FROM edges e WHERE (e.record_id,e.i)=(n.record_id,n.i))),
        material_keys AS MATERIALIZED (
            SELECT DISTINCT record_id,norm FROM projected WHERE kind='part' AND norm IS NOT NULL),
        axes AS (
            SELECT record_id,norm,position FROM (
                SELECT record_id,norm,max(position) OVER w AS position,count(norm) OVER w AS materials
                FROM (SELECT record_id,norm,NULL::bigint AS position FROM material_keys
                      UNION ALL SELECT record_id,NULL,position FROM ordered) keys
                WINDOW w AS (PARTITION BY record_id)) m WHERE norm IS NOT NULL OR materials=0),
        buckets AS (
            SELECT a.record_id,a.position,a.norm AS material,q.i,
              CASE WHEN q.constant_filter THEN '[]'::jsonb ELSE coalesce(to_jsonb(array_agg(
                DISTINCT p.raw COLLATE "C" ORDER BY p.raw COLLATE "C" NULLS FIRST)
                FILTER (WHERE p.i IS NOT NULL)),'[]'::jsonb) END AS raw_key,
              coalesce(jsonb_agg(DISTINCT jsonb_build_array(p.raw,p.name,p.link,p.norm))
                FILTER (WHERE p.i IS NOT NULL),'[]'::jsonb) AS labels, bool_and(p.proved) AS proved
            FROM axes a CROSS JOIN requested q
            LEFT JOIN projected p ON p.record_id=a.record_id AND p.i=q.i
                AND (q.kind IS DISTINCT FROM 'part' OR p.norm=a.norm OR p.norm IS NULL)
            GROUP BY a.record_id,a.position,a.norm,q.i,q.constant_filter),
        vectors AS (
            SELECT record_id,position,material,jsonb_agg(raw_key ORDER BY i) AS signature,
                jsonb_agg(labels ORDER BY i) AS labels,bool_and(proved) AS proved
            FROM buckets GROUP BY record_id,position,material),
        members AS (SELECT DISTINCT ON (record_id,signature) * FROM vectors
            ORDER BY record_id,signature,material COLLATE "C" NULLS LAST)
        ,result_groups AS (SELECT signature,count(*) AS count,(array_agg(record_id ORDER BY position,material COLLATE "C"))[1] AS representative,
               jsonb_agg(DISTINCT labels) AS labels,bool_and(proved) AS proved,
               min(position) AS position,min(material COLLATE "C") AS first_material
        FROM members GROUP BY signature)""")
    return group_query, args


def execute(plan, permission_scopes, *, connection=None, _unresolved_only=False,
            _result_groups=False, _record_ids=None, _admit=None, _restricted=False, source_revision_sha256=None,
            _deadline=None, _native_source_families=None, _summary_source_families=None,
            _summary_selector=None, _require_unresolved_summary=False):
    """Count authorized matching data records and page them in deterministic order.

    Each row contains every value. 'returned' selects requested values by name;
    'group_keys' reports all distinct normalized values for the grouping field.
    total counts distinct records. The 料件 grouping pages distinct record/part
    memberships and returns their count separately in grouped_total.
    """
    if not isinstance(plan, dict) or set(plan) - {"filters", "return", "group_by", "limit", "offset",
                                                 "order_by", "include_unmapped_text", "column_variants"}:
        raise ValueError("invalid record query plan")
    rank_projection = plan.get("order_by") == "projection_coverage"
    if plan.get("order_by") not in (None, "projection_coverage") or plan.get("include_unmapped_text", True) is not True:
        raise ValueError("unsupported record query option")
    filters, returns, group = plan.get("filters", []), plan.get("return", []), plan.get("group_by")
    limit, offset = plan.get("limit", 100), plan.get("offset", 0)
    if not isinstance(filters, list) or not all(isinstance(f, dict) for f in filters) or not isinstance(returns, list):
        raise ValueError("invalid filter or return list")
    if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
        raise ValueError("invalid record query page")
    if not isinstance(permission_scopes, (list, tuple, set, frozenset)):
        raise ValueError("expected authorized scope ids")
    scopes = [_text(scope) for scope in permission_scopes]
    column_variants = plan.get("column_variants", {})
    if (not isinstance(column_variants, dict) or any(_column(prop) is None or not isinstance(names, list)
            or not names or any(not isinstance(name, str) or not name.strip()
                or field_name_key(name) != field_name_key(_column(prop)) for name in names)
            for prop,names in column_variants.items())):
        raise ValueError("invalid raw column variants")
    bounds = range_bounds(filters)
    non_range_filters = [f for f in filters if f.get("op") not in ("gte", "lte")]
    non_range_terms = [_filter_ids(f, column_variants) for f in non_range_filters]
    partial_dates = {f["property"] for f in non_range_filters
                     if f.get("op") == "contains" and PROPERTY_TYPES.get(f.get("property")) == "date"}
    comparison_properties = list(dict.fromkeys([*bounds, *sorted(partial_dates)]))
    non_comparison_terms = [term for f, term in zip(non_range_filters, non_range_terms, strict=True)
                           if not (f.get("op") == "contains" and f.get("property") in partial_dates)]
    # Count each unresolved value once after non-comparison filters. The restricted
    # source reader can request the same candidates and apply its family/selector.
    unresolved_sql = sql.SQL("SELECT v.record_id FROM record_value v JOIN visible USING(record_id) "
                             "WHERE v.property_id=ANY(%s) AND v.norm_status <> 'ok'")
    unresolved_args = [comparison_properties]
    for subquery, args in non_comparison_terms:
        unresolved_sql += sql.SQL(" AND v.record_id IN ({})").format(subquery)
        unresolved_args.extend(args)
    if _unresolved_only:
        terms = [(unresolved_sql, unresolved_args)]
    else:
        terms = [*non_range_terms, *(_range_ids(prop, values) for prop, values in bounds.items())]
    material_groups = group == "料件"
    group_type = "part" if material_groups else ENTITY_TYPES.get(group)
    props = [f["property"] for f in filters] + returns + ([group] if group is not None and not material_groups else [])
    raw_columns = {name for prop in props for name in _column_names(prop, column_variants)}
    if not scopes:
        empty = {"total": 0, "rows": [], "truncated": False, "grouped_total": 0, "unlinked_count": 0}
        if _result_groups:
            empty["result_groups"] = []
        if rank_projection:
            empty.update(without_projection=0, quantity_only=0)
        if comparison_properties:
            empty["unresolved_value_count"] = 0
        return empty

    eligibility = sql.SQL("")
    if source_revision_sha256 is not None:
        pin = sql.Literal(_hash(source_revision_sha256))
        eligibility = sql.SQL(" AND verified_at_export AND export_binding IS NOT NULL AND (CASE WHEN kind='table_row' THEN source_revision_sha256 ELSE fact_serving_revision_sha256 END)={}").format(pin)
    qualified_native = source_revision_sha256 is not None and _native_source_families is not None
    native_family_narrowed = False
    if qualified_native:
        native_scope, native_family_narrowed = _native_family_scope(_native_source_families)
        eligibility += native_scope
    visible = sql.SQL("""WITH visible AS NOT MATERIALIZED (
        SELECT * FROM record WHERE permission_scope=ANY(%s)
        AND coalesce(row_role,'') NOT IN ('header', 'header_candidate'){}) """).format(eligibility)
    params = [scopes]
    where = sql.SQL("")
    for i, (subquery, args) in enumerate(terms):
        where += sql.SQL(" AND " if i else " WHERE ") + sql.SQL("record_id IN ({})").format(subquery)
        params.extend(args)
    if _record_ids is not None:
        where += sql.SQL(" AND " if terms else " WHERE ") + sql.SQL("record_id=ANY(%s)")
        params.append(_record_ids)
    match_params = params.copy()
    groups = sql.SQL("ARRAY[]::text[]")
    if group_type:
        groups = sql.SQL("""ARRAY(SELECT DISTINCT e.norm_key FROM record_entity re JOIN entity e USING(entity_id)
            WHERE re.record_id=m.record_id AND e.entity_type=%s ORDER BY e.norm_key)""")
        params.append(group_type)
    elif group is not None:
        col = _column(group)
        label, value = ("column_name_raw", "column_text_norm") if col is not None else ("property_id", "norm_value")
        groups = sql.SQL("""ARRAY(SELECT DISTINCT v.{value} FROM record_value v WHERE v.record_id=m.record_id
            AND v.{label}{comparison} AND v.{value} IS NOT NULL ORDER BY v.{value})""").format(
                comparison=sql.SQL("=ANY(%s)" if col is not None else "=%s"),
                label=sql.Identifier(label), value=sql.Identifier(value))
        params.append(_column_names(group, column_variants) if col is not None else group)
    memberships = (sql.SQL("""SELECT record_id, ARRAY(SELECT key WHERE key IS NOT NULL) AS group_keys
                      FROM grouped LEFT JOIN LATERAL unnest(group_keys) AS k(key) ON true""")
                   if material_groups else sql.SQL("SELECT * FROM grouped"))
    # Rank the full scoped match set before LIMIT so an early page of identity
    # fragments cannot hide later records with requested values.
    if rank_projection:
        if not returns or group is not None:
            raise ValueError("projection ranking requires ungrouped return fields")
        # Count both ontology and literal-column projections if the same cell
        # supplies both. An entity edge fills a missing part projection once.
        projected_slots = [_column_names(label, column_variants) for label in returns if label.startswith("column:")]
        projected_cols = list({name for names in projected_slots for name in names})
        columns = sql.SQL("0")
        column_date = sql.SQL("false")
        if projected_cols:
            columns = sql.SQL(" + ").join(sql.SQL("coalesce(bool_or(v.column_name_raw=ANY(%s)),false)::int") for _ in projected_slots)
            column_date = sql.SQL("v.column_name_raw=ANY(%s)")
        hits = sql.SQL("count(DISTINCT v.property_id) FILTER (WHERE v.property_id=ANY(%s)) + ") + columns
        params.append(returns)
        if projected_cols:
            params.extend(projected_slots)
        params.append(returns)
        if projected_cols:
            params.append(projected_cols)
        extra = sql.SQL("false")
        if "part_number" in returns:
            extra = sql.SQL("""NOT c.has_part AND EXISTS (
                SELECT FROM record_entity re JOIN entity e USING(entity_id)
                WHERE re.record_id=m.record_id AND e.entity_type='part')""")
        ranking = sql.SQL("""SELECT m.*, c.hits + l.linked::int AS hits, c.newest,
            (c.hits=1 AND c.has_quantity AND NOT l.linked) AS quantity_only
            FROM memberships m CROSS JOIN LATERAL (
            SELECT {} AS hits, max(v.norm_value) FILTER (WHERE v.value_type='date' AND
               (v.property_id=ANY(%s) OR {})) AS newest,
               coalesce(bool_or(v.property_id='part_number'),false) AS has_part,
               coalesce(bool_or(v.property_id='quantity'),false) AS has_quantity
            FROM record_value v WHERE v.record_id=m.record_id AND nullif(btrim(v.raw_value),'') IS NOT NULL
            ) c CROSS JOIN LATERAL (SELECT {} AS linked) l""").format(hits,column_date,extra)
        if "quantity" not in returns:
            ranking = sql.SQL("SELECT record_id,group_keys,hits,newest,false AS quantity_only FROM ({}) q").format(ranking)

    else:
        ranking = sql.SQL("SELECT m.*, 0 AS hits, NULL::text AS newest, false AS quantity_only FROM memberships m")
    match_prefix = visible + sql.SQL(", matched AS MATERIALIZED (SELECT record_id FROM visible {})").format(where)
    rank_prefix = sql.SQL(""", grouped AS MATERIALIZED (SELECT m.record_id, {} AS group_keys FROM matched m),
        memberships AS ({}), ranked AS MATERIALIZED ({})""").format(groups, memberships, ranking)
    group_field = sql.SQL("")
    if _result_groups:
        if not rank_projection:
            raise ValueError("table result groups require projection ranking")
        group_query, group_args = _record_result_groups(returns, filters, bounds, column_variants)
        rank_prefix += group_query
        params.extend(group_args)
        group_field = sql.SQL(""", (SELECT coalesce(jsonb_agg(jsonb_build_array(signature,count,representative,labels,proved)
                            ORDER BY position,first_material COLLATE "C",signature),'[]'::jsonb) FROM result_groups)""")
    page_sql = sql.SQL(""",
        page AS (SELECT * FROM ranked ORDER BY hits DESC, newest DESC NULLS LAST, group_keys, record_id LIMIT %s OFFSET %s)
        SELECT (SELECT count(*) FROM grouped), (SELECT count(*) FROM memberships), (SELECT count(*) FROM grouped WHERE cardinality(group_keys)=0),
        (SELECT count(*) FROM ranked WHERE hits=0), (SELECT count(*) FROM ranked WHERE quantity_only),
        coalesce(jsonb_agg((to_jsonb(r) - ARRAY['import_key','export_members','verified_at_export','source_revision_sha256','export_binding','fact_serving_revision_sha256']) ||
            jsonb_build_object('projection_hits',p.hits,'projection_date',p.newest,'quantity_only',p.quantity_only,
                'values', vals.fields, 'group_keys', p.group_keys, 'entities', links.entities,
                'export_row_ids', ARRAY(SELECT jsonb_object_keys(r.export_members) ORDER BY 1))
            ORDER BY p.hits DESC,p.newest DESC NULLS LAST,p.group_keys,p.record_id) FILTER (WHERE p.record_id IS NOT NULL), '[]'::jsonb){}
        FROM page p JOIN record r USING(record_id)
        CROSS JOIN LATERAL (SELECT jsonb_agg(to_jsonb(v) - 'record_id' - 'column_text_norm' ORDER BY v.ordinal) AS fields
            FROM record_value v WHERE v.record_id=p.record_id) vals
        CROSS JOIN LATERAL (SELECT coalesce(jsonb_agg(jsonb_build_object(
            'entity_type', e.entity_type, 'norm_key', e.norm_key, 'raw_key', re.raw_key, 'citation_hash', re.citation_hash,
            'via_property', re.via_property, 'via', CASE WHEN re.via_property='quote_mention' THEN 'quote_mention'
            ELSE 'value' END) ORDER BY e.entity_type, e.norm_key, re.via_property), '[]'::jsonb) AS entities
            FROM record_entity re JOIN entity e USING(entity_id) WHERE re.record_id=p.record_id) links""").format(group_field)
    with _transaction(connection) as db:
        def remaining_budget():
            if _deadline is not None:
                ms = int(1000 * (_deadline - time.monotonic()))
                if ms <= 0:
                    raise TimeoutError("record query deadline")
                db.execute("SELECT set_config('statement_timeout',%s,true)", (str(ms),))
        entity_filters = [item for item in filters if item.get("property") in ENTITY_TYPES
                          and item.get("op") in ("eq", "in", "contains")]
        if _admit is not None and entity_filters:
            seed_tests, seed_args = [], []
            for item in entity_filters:
                prop, op = item["property"], item["op"]
                keys = [normalize("identifier", str(value))["norm"] for value in item["values"]]
                test = sql.SQL("strpos(e.norm_key,%s)>0" if op == "contains" else "e.norm_key=ANY(%s)")
                seed_tests.append(sql.SQL("(seed.via_property=%s AND e.entity_type=%s AND {})").format(test))
                seed_args.extend([prop, ENTITY_TYPES[prop], keys[0] if op == "contains" else keys])
            seed_prefix = visible + sql.SQL(""", matched AS MATERIALIZED (
                SELECT DISTINCT seed.record_id FROM record_entity seed JOIN entity e USING(entity_id)
                JOIN visible USING(record_id) WHERE {})""").format(sql.SQL(" OR ").join(seed_tests))
            remaining_budget()
            rejected_seeds = _scope_exclusions(db, seed_prefix, [scopes, *seed_args], _admit,
                                               qualified_native=qualified_native)
            if rejected_seeds:
                scoped_eligibility = eligibility + sql.SQL(" AND record_id <> ALL({}::text[])").format(sql.Literal(rejected_seeds))
                visible = sql.SQL("""WITH visible AS NOT MATERIALIZED (
                    SELECT * FROM record WHERE permission_scope=ANY(%s)
                    AND coalesce(row_role,'') NOT IN ('header','header_candidate'){}) """).format(scoped_eligibility)
                match_prefix = visible + sql.SQL(", matched AS MATERIALIZED (SELECT record_id FROM visible {})").format(where)
        if raw_columns:
            for name in raw_columns:
                remaining_budget()
                if not db.execute(visible + sql.SQL("""SELECT EXISTS(SELECT FROM record_value
                    JOIN visible USING(record_id) WHERE column_name_raw=%s LIMIT 1)"""), (scopes,name)).fetchone()[0]:
                    raise ValueError("unavailable raw column")
        if _admit is not None:
            remaining_budget()
            excluded = _scope_exclusions(db, match_prefix, match_params, _admit, qualified_native=qualified_native)
            if excluded:
                where += sql.SQL(" AND " if terms or _record_ids is not None else " WHERE ")
                where += sql.SQL("record_id <> ALL(%s)")
                params.insert(len(match_params), excluded)
                match_prefix = visible + sql.SQL(", matched AS MATERIALIZED (SELECT record_id FROM visible {})").format(where)
        for prop,names in column_variants.items():
            if len(names) < 2:
                continue
            remaining_budget()
            conflict = db.execute(match_prefix + sql.SQL("""SELECT FROM record_value v JOIN matched USING(record_id)
                WHERE v.column_name_raw=ANY(%s) GROUP BY v.record_id
                HAVING count(DISTINCT v.column_name_raw)>1 AND count(DISTINCT v.raw_value)>1 LIMIT 1"""),
                [*params[:len(match_params)+(1 if _admit is not None and excluded else 0)],names]).fetchone()
            if conflict is not None:
                raise ValueError("unavailable raw column")
        prefix = match_prefix + rank_prefix
        query = prefix + page_sql
        remaining_budget()
        total, grouped_total, unlinked, missing, quantity_only, rows, *group_result = db.execute(
            query, [*params, limit, offset]).fetchone()
        comparison = {"result_groups":[tuple(g) for g in group_result[0]]} if group_result else {}
        summary = None
        if comparison_properties and not _unresolved_only:
            remaining_budget()
            summary = _unresolved_summary_count(db, scopes, source_revision_sha256, comparison_properties,
                families=_summary_source_families, selector=_summary_selector, restricted=_restricted,
                unsupported=bool(non_comparison_terms) or _record_ids is not None, required=_require_unresolved_summary)
            if summary is not None:
                comparison.update(summary)
        if comparison_properties and not _unresolved_only and _record_ids is None and summary is None:
            count_query = visible + sql.SQL("SELECT count(*) FROM ({}) skipped").format(unresolved_sql)
            count_params = [scopes, *unresolved_args]
            fast_unresolved_count = len(scopes) <= 16 and not non_comparison_terms and not native_family_narrowed
            if fast_unresolved_count:
                # Exclude the indexed gaps between grants and the headers inside them.
                # Use the database collation for text boundaries. Larger grant lists
                # retain the positive visible join above without growing a UNION.
                ordered = scopes
                if len(scopes) > 1:
                    remaining_budget()
                    ordered = [r[0] for r in db.execute("SELECT DISTINCT s FROM unnest(%s::text[]) s ORDER BY s",
                                                        (scopes,)).fetchall()]
                excluded_sql = """SELECT record_id FROM record WHERE permission_scope < %s
                    UNION ALL SELECT record_id FROM record WHERE permission_scope > %s
                    UNION ALL SELECT record_id FROM record WHERE permission_scope=ANY(%s)
                      AND coalesce(row_role,'') IN ('header','header_candidate')"""
                count_params = [ordered[0], ordered[-1], ordered]
                for lower, upper in zip(ordered, ordered[1:]):
                    excluded_sql += " UNION ALL SELECT record_id FROM record WHERE permission_scope>%s AND permission_scope<%s"
                    count_params.extend([lower,upper])
                if source_revision_sha256 is not None:
                    excluded_sql += """ UNION ALL SELECT record_id FROM record WHERE NOT verified_at_export
                        OR export_binding IS NULL OR (kind='table_row' AND source_revision_sha256 IS NULL)
                        OR (kind IN ('pdf_line','passage') AND fact_serving_revision_sha256 IS NULL)"""
                    for condition, column in (("kind='table_row'", "source_revision_sha256"),
                                              ("kind IN ('pdf_line','passage')", "fact_serving_revision_sha256")):
                        for operator in ("<", ">"):
                            excluded_sql += (f" UNION ALL SELECT record_id FROM record WHERE {condition}"
                                f" AND verified_at_export AND export_binding IS NOT NULL AND {column} {operator} %s")
                            count_params.append(source_revision_sha256)
                count_query = f"""WITH omitted AS MATERIALIZED ({excluded_sql}) SELECT count(*) FROM record_value v
                    WHERE v.property_id=ANY(%s) AND v.norm_status<>'ok'
                    AND NOT EXISTS (SELECT FROM omitted WHERE omitted.record_id=v.record_id)"""
                count_params.append(comparison_properties)
            if _restricted and _admit is not None:
                skipped = visible + sql.SQL(", matched AS MATERIALIZED (SELECT DISTINCT record_id FROM ({}) u)").format(unresolved_sql)
                remaining_budget()
                excluded = _scope_exclusions(db, skipped, [scopes, *unresolved_args], _admit, qualified_native=qualified_native)
                if fast_unresolved_count and qualified_native:
                    # Both native families share the sealed admission. Keep the
                    # existing indexed scope/revision omission count, subtracting
                    # only callback-rejected fact/legacy records.
                    count_query += " AND v.record_id <> ALL(%s)"
                    count_params.append(excluded)
                else:
                    count_query = visible + sql.SQL("SELECT count(*) FROM ({}) u WHERE record_id <> ALL(%s)").format(unresolved_sql)
                    count_params = [scopes, *unresolved_args, excluded]
            remaining_budget()
            comparison["unresolved_value_count"] = db.execute(count_query, count_params).fetchone()[0]
    for row in rows:
        if not rank_projection:
            for key in ("projection_hits", "projection_date", "quantity_only"):
                row.pop(key)
        if material_groups:
            row["group_via"] = None
            if row["group_keys"]:
                row["group_via"] = ("value" if any(e["via"] == "value" and e["entity_type"] == "part"
                    and e["norm_key"] == row["group_keys"][0] for e in row["entities"]) else "quote_mention")
        if group_type and not row["group_keys"]:
            row["group_keys"] = ["未連到料件" if group_type == "part" else "未連到採購單"]
        if returns:
            row["returned"] = {}
            for prop in returns:
                column = _column(prop)
                key, match = ("column_name_raw", column) if column is not None else ("property_id", prop)
                row["returned"][prop] = [value for value in row["values"] if
                    (value[key] in _column_names(prop, column_variants) if column is not None else value[key] == match)]
    return {**comparison, **({"without_projection": missing, "quantity_only": quantity_only} if rank_projection else {}),
            "total": total, "rows": rows, "truncated": offset + len(rows) < grouped_total,
            "grouped_total": grouped_total, "unlinked_count": unlinked if group_type else 0}
