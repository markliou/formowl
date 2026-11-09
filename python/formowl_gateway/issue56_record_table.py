"""Bridge the local, permission-scoped record store to sealed candidate source verification."""
from collections import defaultdict
from pathlib import Path
from functools import lru_cache
import json
import logging
import os
import re
import time
import unicodedata

from formowl_contract import ContractValidationError, redact_public_raw_references, sha256_json, to_plain
from formowl_mail.hybrid import _semantic_observation_retrieval_source_family
from formowl_mail.issue56_sealed_source import _authorized_mail_selector_for_asset

_SECRET = Path("/run/secrets/formowl-record-reader")
_LOG = logging.getLogger(__name__)
_RECORD_PROOF_PAGE = 20
_MAJOR_ALIAS_LIMIT = 3


class RecordFieldValidationError(ContractValidationError):
    """A field resolution failure with bounded public capability guidance."""

    def __init__(self, capabilities):
        self.guidance = _field_guidance(capabilities)
        super().__init__("record table field is unknown or ambiguous; " + self.guidance)


@lru_cache(maxsize=1)
def _ontology_aliases():
    path = Path(__file__).parents[1] / "formowl_records" / "data" / "ontology_aliases.json"
    return json.loads(path.read_text())["ontology_aliases"]


def _safe_field_alias(label):
    if (not isinstance(label, str) or not label.strip() or len(label) > 120
            or redact_public_raw_references(label)[1]):
        return False
    normalized = unicodedata.normalize("NFKC", label).strip()
    # Values mistaken for headers must never become field aliases. This
    # deliberately rejects digit-bearing phrases too: a column label containing
    # a product/order code or a date is still a derived data value.
    numeric = any(char.isnumeric() for char in normalized)
    return not (label.strip().isnumeric() or normalized.isnumeric()
                or (numeric and (len(normalized) >= 4 or any(char in "年月日" for char in normalized)
                                 or not any(char.isalpha() for char in normalized))))


def _private_aliases():
    # Derived source labels are operator data, never package data. An unset or
    # unavailable private mount leaves the generic ontology vocabulary usable.
    configured = os.environ.get("FORMOWL_RECORD_ALIASES_PATH", "").strip()
    if not configured:
        return None
    try:
        payload = json.loads(Path(configured).read_text())
    except (OSError, ValueError):
        _LOG.warning("record_table_aliases_unavailable")
        return None
    if not isinstance(payload, dict):
        return None
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        return None
    return {prop: list(dict.fromkeys(label for label in labels if _safe_field_alias(label)))
            for prop, labels in properties.items() if isinstance(labels, list)}


def _mapped_aliases():
    return _private_aliases() or {}


def _property_aliases(capabilities, *, include_capabilities=False):
    from formowl_records.store import PROPERTY_TYPES

    props = {prop: [] for prop in PROPERTY_TYPES}
    private = _private_aliases()
    sources = [_ontology_aliases()]
    if include_capabilities or private is not None:
        sources.append(capabilities.get("properties", {}))
    if private is not None:
        sources.append(private)
    for source in sources:
        for prop, labels in source.items():
            if prop in props and isinstance(labels, (list, tuple)):
                props[prop].extend(label for label in labels if _safe_field_alias(label) and label != prop)
    return {prop: list(dict.fromkeys(labels)) for prop, labels in props.items()}


def _field_guidance(capabilities):
    major = {prop: labels[:_MAJOR_ALIAS_LIMIT] for prop, labels in _property_aliases(capabilities).items()}
    return "Available record properties and major aliases: " + json.dumps(major, ensure_ascii=False, separators=(",", ":")) + "; use column:<authorized raw column> for literal columns."



def _connection(deadline):
    import psycopg

    remaining_ms = int((deadline - time.monotonic()) * 1000)
    if remaining_ms <= 0:
        raise TimeoutError
    return psycopg.connect(host="127.0.0.1", port=55432, user="formowl_record_reader", dbname="formowl",
        password=_SECRET.read_text().strip(), connect_timeout=2,
        options=f"-c default_transaction_read_only=on -c statement_timeout={remaining_ms}")


def catalog(revision):
    if not getattr(revision, "candidate_fact_pin", None) or not _SECRET.is_file():
        return {}
    import psycopg
    from formowl_records.store import PROPERTY_TYPES

    try:
        with _connection(time.monotonic() + 2) as db:
            rows = db.execute("""SELECT DISTINCT v.column_name_raw FROM record_value v JOIN record r USING(record_id)
                WHERE r.permission_scope=ANY(%s) AND v.column_name_raw IS NOT NULL
                AND coalesce(r.row_role,'') NOT IN ('header','header_candidate')
                AND r.verified_at_export AND r.export_binding IS NOT NULL
                AND (CASE WHEN r.kind='table_row' THEN r.source_revision_sha256 ELSE r.fact_serving_revision_sha256 END)=%s
                AND length(v.column_name_raw) BETWEEN 1 AND 120 ORDER BY 1 LIMIT 129""",
                (list(revision.authorized_source.source_scope_ids), revision.safe_binding["source_revision_sha256"])).fetchall()
    except (OSError, psycopg.Error):
        _LOG.warning("record_table_catalog_unavailable")
        rows = []
    props = {prop: [] for prop in PROPERTY_TYPES}
    for label, prop in revision.candidate_fact_rows.aliases:
        if prop in props and label != prop and _safe_field_alias(label):
            props[prop].append(label)
    props = {prop: labels[:_MAJOR_ALIAS_LIMIT] for prop, labels in _property_aliases({"properties": props}).items()}
    return {"properties": props, "raw_columns": [s for s, in rows[:128] if not redact_public_raw_references(s)[1]],
            "raw_column_listing_truncated": len(rows) > 128}


def _fold(text):
    from formowl_records.store import field_name_key
    return field_name_key(text)


def _field_resolver(capabilities, *, include_capabilities=False):
    aliases = defaultdict(set)
    for prop, labels in _property_aliases(capabilities, include_capabilities=include_capabilities).items():
        for label in [prop, *labels]:
            aliases[_fold(label)].add(prop)

    def resolve(label, *, strict=True):
        from formowl_records.store import PROPERTY_TYPES
        if not isinstance(label, str) or len(label) > 120 or redact_public_raw_references(label)[1]:
            if strict:
                raise RecordFieldValidationError(capabilities)
            return None
        if label in PROPERTY_TYPES:
            return label
        # Explicit namespace never goes through ontology aliases. The executor
        # checks the raw column against authorized, pinned visible records.
        normalized = unicodedata.normalize("NFKC", label)
        if _fold(normalized).startswith("column:") and normalized.partition(":")[2].strip():
            return "column:" + normalized.partition(":")[2].strip()
        matches = aliases.get(_fold(label), set())
        if len(matches) == 1:
            return next(iter(matches))
        raw_matches = {raw for raw in capabilities.get("raw_columns", ()) if _fold(raw) == _fold(label)}
        if not matches and (label in raw_matches or len(raw_matches) == 1):
            return "column:" + (label if label in raw_matches else next(iter(raw_matches)))
        if strict:
            raise RecordFieldValidationError(capabilities)
        return None
    return resolve


def structured_query_guidance(capabilities, contract):
    """Offer schema help only. A description match never creates a predicate."""
    generic = _ontology_aliases()
    offered = {prop: generic[prop][:2] for prop in capabilities["properties"] if prop in generic}
    if not offered:
        return None
    if contract.get("query_class") != "exact_set_or_inventory":
        descriptions = [unicodedata.normalize("NFKC", field).casefold()
                        for field in contract.get("requested_fields", ())]
        if not descriptions:
            return None
        resolver = _field_resolver(capabilities)
        if not any(resolver(field, strict=False) in offered for field in descriptions):
            # A known label can also occur inside a longer field description.
            # This supplementary match offers help; it never binds a filter.
            names = defaultdict(set)
            for prop, labels in _property_aliases(capabilities).items():
                if prop in offered:
                    for label in (prop, *labels):
                        name = unicodedata.normalize("NFKC", label).strip().casefold()
                        if len(name) >= 2:
                            names[name].add(prop)
            pattern = "|".join(re.escape(name) for name, props in names.items() if len(props) == 1)
            if not pattern or not any(re.search(r"(?<![a-z0-9_])(?:" + pattern + r")(?![a-z0-9_])", field)
                                      for field in descriptions):
                return None
    return {
        "guidance": "可用的結構化查詢。若需依欄位列出結果，可在目前授權範圍內以明確的篩選值再次呼叫 query_effective_graph_view。請將格式中的佔位符替換為實際參數。",
        "properties": offered,
        "table_query": {"filters": [{"field": "<property>", "op": "eq", "value": "<value>"}],
                        "projection_fields": ["<property>"]},
    }


def plan_for(query, capabilities, requested):
    from formowl_mail.human_uat_orchestrator import _validate_table_query
    from formowl_records.store import range_bounds
    _validate_table_query(query)
    resolve = _field_resolver(capabilities)
    # The explicit projection is authoritative. requested_fields is a semantic
    # information-need description, and need not be a literal column list.
    projections = list(dict.fromkeys(resolve(label) for label in query["projection_fields"]))
    predicates = []
    for item in query["filters"]:
        if len(item["value"]) > 400:
            raise ContractValidationError("invalid record filter value")
        predicates.append({"property": resolve(item["field"]), "op": item.get("op", "eq"), "values": [item["value"]]})
    try:
        range_bounds(predicates)
    except ValueError as exc:
        raise ContractValidationError(str(exc)) from None
    return {"filters": predicates, "return": projections, "limit": 128, "order_by": "projection_coverage"}


def _automatic_plan(required_terms, capabilities, requested, scopes, pin, db, *, admit=None, native_families=None):
    from formowl_records.normalize import normalize
    from formowl_records.store import ENTITY_TYPES, PROPERTY_TYPES, known_entity_filters
    resolve = _field_resolver(capabilities, include_capabilities=True)
    hints = {}
    for term in required_terms:
        parts = term.rsplit(None, 1)
        if len(parts) == 2 and (prop := resolve(parts[0], strict=False)) in ENTITY_TYPES:
            hints[normalize("identifier", term)["norm"]] = prop
    predicates, ambiguous = known_entity_filters(required_terms, scopes, source_revision_sha256=pin, connection=db,
        _admit=admit, _native_source_families=native_families, _term_identity_hints=hints)
    if ambiguous:
        return None, "ambiguous_entity"
    if not predicates:
        return None, "no_known_entity"
    projections = list(dict.fromkeys(prop for label in requested if (prop := resolve(label, strict=False))))
    if not projections:
        projections = list(PROPERTY_TYPES)
    return {"filters": predicates, "return": projections, "limit": 128, "order_by": "projection_coverage"}, None


def _resolve_raw_plan(plan, scopes, pin, db, *, admit=None, native_families=None, deadline=None, fact_columns=None):
    from formowl_records.store import resolve_raw_columns

    labels = [*plan["return"], *(item["property"] for item in plan["filters"])]
    raw = {label.removeprefix("column:") for label in labels if label.startswith("column:")}
    if not raw:
        return plan
    resolved = resolve_raw_columns(raw, scopes, source_revision_sha256=pin, connection=db,
        _admit=admit, _native_source_families=native_families, _deadline=deadline, _fact_columns=fact_columns,
        _query_filters=plan["filters"])
    return {**plan, "column_variants": {"column:"+label: names for label,names in resolved.items()}}


def _native_batch(records, budget, *, deadline=None, stage=False, require_complete=False, priority_refs=()):
    """Hydrate each nominated row once through the sealed exact owner's shard scan."""
    from formowl_gateway.issue56_sealed_source_loader import _table_row_key
    lookup = budget["exact_lookup"]
    if lookup is None:
        raise ContractValidationError("native record exact source is unavailable")
    expected, scopes, cell_rows = {}, {}, {}
    for record in records:
        digest = record["source_hash"]
        members = expected.setdefault(digest, {})
        if members.setdefault(digest, record["source_observation_id"]) != record["source_observation_id"]:
            raise ContractValidationError("ambiguous native row binding")
        if scopes.setdefault(digest, record["permission_scope"]) != record["permission_scope"]:
            raise ContractValidationError("ambiguous native scope")
        for value in record["values"]:
            for span in (*value["evidence_spans"], *value.get("context_spans", ())):
                key, oid = span["observation_hash"], span["observation_id"]
                if members.setdefault(key, oid) != oid:
                    raise ContractValidationError("ambiguous native source binding")
                if key != digest and cell_rows.setdefault(key, digest) != digest:
                    raise ContractValidationError("ambiguous native cell binding")
    if not expected:
        return {}
    # The preferred scan accepts at most 128 nominations. Stage public evidence
    # for nominated cells, keeping at least one locator for each distinct row.
    preferred = dict.fromkeys(expected)
    staged_rows = {}
    if stage:
        for key in dict.fromkeys([*(ref for ref in priority_refs if ref in cell_rows), *cell_rows]):
            row = cell_rows[key]
            if row in preferred:
                del preferred[row]
            if len(preferred) < 128:
                preferred[key] = None
                staged_rows[key] = row
    verified, observations, evidence = {}, {}, {}
    def collect(group):
        members = {sha256_json(item.to_dict()):item for item in group[1:]}
        for row_key in members.keys() & expected.keys():
            wanted = expected[row_key]
            row = members[row_key]
            if (row.observation_type != "table_row" or row.permission_scope["scope_id"] != scopes[row_key]
                    or any(key not in members or members[key].observation_id != oid for key,oid in wanted.items())
                    or any(members[key].observation_type != "table_cell"
                           or _table_row_key(members[key]) != _table_row_key(row)
                           or members[key].permission_scope != row.permission_scope
                           or members[key].extractor_run_id != row.extractor_run_id for key in wanted if key != row_key)):
                continue
            verified[row_key] = {key:members[key] for key in wanted}

    def observe(item, scope):
        if stage:
            observations[item.observation_id] = item
        return True

    remaining = budget["max_reads"] - budget["reads"]
    deadline = min(budget["deadline"], deadline or budget["deadline"])
    if remaining <= 0 or time.monotonic() >= deadline:
        if require_complete:
            raise TimeoutError("native record permission deadline")
        return {}
    metrics = {}
    try:
        scan = lookup.scan_source_rows(required_terms=(), query_text="", source_families=budget["record_families"],
            mail_import_session_id=budget["record_selector"], max_observations=remaining,
            deadline_monotonic=deadline, observation_callback=observe, native_group_callback=collect,
            evidence_by_id=evidence, _phase_metrics=metrics, preferred_observation_hashes=tuple(preferred),
            **({"_member_row_hashes":staged_rows} if staged_rows else {}))
    finally:
        budget["reads"] += metrics.get("scanned_observation_count", 0)
    if require_complete and scan.stop_reason != "source_table_shortlist":
        raise ContractValidationError("incomplete native record scope check")
    if stage:
        receipts = budget.setdefault("staged_native_evidence", {})
        for key, row_key in staged_rows.items():
            member = verified.get(row_key, {}).get(key)
            if member is not None and member.observation_id in observations and member.observation_id in evidence:
                receipts[key] = (member, evidence[member.observation_id])
    return verified


def _preferred_native_members(record, budget):
    result = _native_batch([record], budget)
    if record["source_hash"] not in result:
        raise ContractValidationError("missing native record member")
    return result[record["source_hash"]]


def _normalized_field(value):
    normalized = value.get("norm_value") if value.get("norm_status") == "ok" else None
    if normalized is None:
        return {}
    if not isinstance(normalized, str) or redact_public_raw_references(normalized)[1]:
        raise ValueError("unavailable public normalized value")
    return {"_record_normalized": normalized}


def _native_fields(record, revision, budget):
    # Prefer the already admitted source members when this is a detail or group anchor.
    members = record.get("_source_members")
    if members is None:
        members = _preferred_native_members(record, budget)
    row = members[record["source_hash"]]
    if row.observation_type != "table_row" or row.permission_scope["scope_id"] != record["permission_scope"]:
        raise ValueError("invalid row")
    fields = []
    for value in record["values"]:
        cell = members[value["citation_hash"]]
        label = (cell.payload.get("table_structure") or {}).get("column_name")
        if isinstance(label, str):
            label = redact_public_raw_references(label)[0] if label.strip() else None
        raw = cell.text or ""
        if label != value["column_name_raw"] or redact_public_raw_references(raw)[0] != value["raw_value"]:
            raise ValueError("native cell changed")
        anchor, path = raw, ["text"]
        if not raw:
            anchor, path = label, ["payload", "table_structure", "column_name"]
        if not anchor or redact_public_raw_references(anchor)[1]:
            continue
        scope = to_plain(cell.permission_scope)
        span = dict(observation_id=cell.observation_id, observation_hash=value["citation_hash"], quote=anchor,
            field_path=path, start=0, end=len(anchor), source_extractor_run_id=cell.extractor_run_id,
            native_locator=to_plain(cell.location))
        budget.setdefault("native_fact_bindings", {})[value["citation_hash"]] = (
            cell.observation_id, record["source_hash"])
        fields.append((value["property_id"], dict(raw_property=label, value=raw, permission_scope=scope, **_normalized_field(value),
            permission_scope_fingerprint=sha256_json(scope), observation_hashes={cell.observation_id:value["citation_hash"]},
            evidence_spans=[span], times=[{"role":role,"normalized":value["norm_value"]} for role in value["date_roles"]])))
    return fields


def _candidate(record, revision, plan, budget, sealed, bounds):
    from formowl_records.normalize import normalize
    from formowl_records.store import ENTITY_TYPES, PROPERTY_TYPES, _identity_keys, matches_range

    context = []
    if record["kind"] == "table_row":
        all_fields = _native_fields(record, revision, budget)
    else:
        all_fields = []
        norms = {(v.get("export_row_id"), v["property_id"], v["column_name_raw"], v["raw_value"],
                  v.get("citation_hash")): _normalized_field(v) for v in record["values"]}
        for rid in record["export_row_ids"]:
            original = sealed.pop(rid)
            for prop, facts in original["fields"].items():
                for fact in facts:
                    raw = None if fact["value"] is None else str(fact["value"])
                    key = (rid, prop, fact.get("raw_property"), raw, fact["evidence_spans"][0]["observation_hash"])
                    all_fields.append((prop, {**fact, **norms.get(key, {})}))
                    spans = [s for t in fact.get("times", ()) for s in t.get("evidence_spans", ())]
                    if spans:
                        context.append({**fact, "evidence_spans": spans})
            context.extend((original.get("subject_identity") or {}).get("sources", ()))
    if not all_fields or any(f["permission_scope"]["scope_id"] != record["permission_scope"]
                             for f in [*(fact for _, fact in all_fields), *context]):
        raise ValueError("record outside scope")

    wanted = list(dict.fromkeys([*plan["return"], *(p["property"] for p in plan["filters"])]))
    fields = {p: [] for p in wanted}
    for prop, fact in all_fields:
        raw_keys = [key for key,names in plan.get("column_variants", {}).items() if fact.get("raw_property") in names]
        for key in dict.fromkeys((prop, "column:" + str(fact.get("raw_property")), *raw_keys)):
            if key in fields and (key not in bounds or matches_range(key, str(fact["value"]), bounds[key])):
                fields[key].append(fact)

    # Rebind every displayed or filtering entity link to its original field or
    # quote. Only these nominated spans can reach the shared source verifier.
    parts, purchase_orders, links, proofs = {}, {}, set(), []
    def matches(candidate, op, target):
        if candidate is None or target is None:
            return False
        return target in candidate if op == "contains" else candidate == target

    entity_filters = defaultdict(list)
    for predicate in plan["filters"]:
        kind = ENTITY_TYPES.get(predicate["property"])
        if kind:
            entity_filters[kind].append((predicate["op"], normalize("identifier", predicate["values"][0])["norm"]))
    for entity in record["entities"]:
        raw, digest, kind, via = (entity[k] for k in ("raw_key", "citation_hash", "entity_type", "via"))
        if not isinstance(raw, str) or not raw:
            continue
        key = entity["norm_key"]
        if kind in entity_filters and not any(matches(key, op, norm) for op, norm in entity_filters[kind]):
            continue
        if kind == "purchase_order" and kind not in entity_filters:
            # A PO projection uses its actual field. Mentions of other PO
            # identifiers are not additional PO values for this record.
            continue
        if via == "value":
            candidates = (fact for prop, fact in all_fields if prop == entity["via_property"]
                          and (key, raw) in _identity_keys(str(fact["value"])))
        elif via == "quote_mention" and normalize("identifier", raw)["norm"] == key:
            candidates = (fact for _, fact in [*all_fields, *((None, f) for f in context)])
        else:
            continue
        for fact in candidates:
            spans = [s for s in fact["evidence_spans"] if s["observation_hash"] == digest
                     and (via == "value" or raw in s["quote"].split())]
            if spans:
                links.add((kind, key))
                proofs.append({**fact, "evidence_spans": spans})
                identities = parts if kind == "part" else purchase_orders
                if key not in identities or via == "value":
                    identities[key] = {"value": raw, "via": via, "column_name_raw": fact.get("raw_property"), "spans": spans}
                break
    for predicate in plan["filters"]:
        prop = predicate["property"]
        if predicate["op"] in ("gte", "lte"):
            if not fields[prop]:
                return None
            continue
        value_type = PROPERTY_TYPES.get(prop, "text")
        target_kind = "text" if value_type == "date" and predicate["op"] == "contains" else value_type
        target = normalize(target_kind, predicate["values"][0])["norm"]
        if target is None or not (any(matches(normalize(value_type, str(f["value"]))["norm"], predicate["op"], target)
                                      for f in fields[prop]) or any(kind == ENTITY_TYPES.get(prop)
                                      and matches(key, predicate["op"], target) for kind, key in links)):
            return None
    for name in tuple(fields):
        if name not in plan["return"]:
            # Filters remain subject to source admission. Their other values do
            # not become additional model-visible projection columns.
            proofs.extend(fields.pop(name))
    fields["_link_proof"] = proofs
    return {"row_id": record["record_id"], "item_or_row": record["record_id"], "_identity_properties": (),
            "fields": fields, "_record_parts": list(parts.values()),
            "_record_orders": list(purchase_orders.values()) if "po_number" in wanted else [],
            "_native_record": record["kind"] == "table_row",
            "_projection_rank": (record["projection_hits"], record["projection_date"] or "")}


def _record_identity_links(record, kind, column):
    """Resolve each stored edge to the same record's field or exact quote token."""
    from formowl_records.normalize import normalize
    from formowl_records.store import _identity_keys, eligible_entity_projection_key
    linked = {}
    edges = [edge for edge in record.get("entities", ()) if edge["entity_type"] == kind
             and eligible_entity_projection_key(kind, edge["norm_key"])]
    direct = [edge for edge in edges if edge["via_property"] == column]
    for entity in direct or edges:
        raw, norm, via = entity["raw_key"], entity["norm_key"], entity["via"]
        if (not isinstance(raw, str) or normalize("identifier", raw)["norm"] != norm
                or redact_public_raw_references(raw)[1]):
            raise ValueError("invalid entity projection")
        if norm in linked and (linked[norm][2] == "value" or via == "quote_mention"):
            continue
        match = None
        for value in record["values"]:
            if via == "value":
                if (value["property_id"] != entity["via_property"] or not isinstance(value["raw_value"], str)
                        or (norm, raw) not in _identity_keys(value["raw_value"])):
                    continue
                spans = [(span, value["column_name_raw"]) for span in value["evidence_spans"]]
            elif via == "quote_mention":
                spans = [(span, value["column_name_raw"]) for span in value["evidence_spans"]]
                spans.extend((span, None) for span in value["context_spans"])
            else:
                raise ValueError("unknown identity edge")
            for span, name in spans:
                if (span["observation_hash"] == entity["citation_hash"]
                        and (via == "value" or raw in span["quote"].split())):
                    if name is not None and redact_public_raw_references(name)[1]:
                        raise ValueError("unavailable public identity column")
                    match = (raw, name, via, value, span)
                    break
            if match is not None:
                break
        if match is None:
            raise ValueError("record identity edge missing source")
        linked[norm] = match
    return linked


def _collect_result_group(groups, record, columns, bounds, equal_fields=()):
    """Use one membership per part. Keep other values together on their original record."""
    from formowl_records.store import ENTITY_TYPES, matches_range
    from formowl_records.normalize import normalize
    projected, material_options = [], {}
    representative = None
    for i, col in enumerate(columns):
        cells = []
        for value in record["returned"][col]:
            raw, name = value["raw_value"], value["column_name_raw"]
            if col in bounds and not matches_range(col, raw, bounds[col]):
                continue
            if any(isinstance(text, str) and redact_public_raw_references(text)[1] for text in (name, raw)):
                raise ValueError("unavailable public result value")
            cells.append((raw, name, None, value, None))
            if representative is None and value["evidence_spans"]:
                representative = value
        kind = ENTITY_TYPES.get(col)
        if kind:
            cells = list(_record_identity_links(record, kind, col).values())
            if not cells and kind == "part":
                cells = [(None, None, "unlinked_part", None, None)]
        if kind == "part":
            options = {}
            for cell in cells:
                key = normalize("identifier", cell[0])["norm"]
                options.setdefault(key, []).append(cell)
            material_options[i] = options
        projected.append(cells)
    # A single material axis prevents multiplying two part-like columns against
    # each other. Multiple PO values stay associated with their common record.
    materials = sorted({key for options in material_options.values() for key in options if key is not None})
    membership_keys = set()
    representative = representative or next((v for v in record["values"] if v["evidence_spans"]), None)
    for material in materials or [None]:
        vector, signature = [], []
        linked_seed = None
        for i, column in enumerate(projected):
            cells = column
            if i in material_options:
                cells = material_options[i].get(material, material_options[i].get(None, []))
            bucket = {}
            for raw, name, link, value, span in cells:
                bucket.setdefault(raw, set()).add((name, link))
                if span is not None and (linked_seed is None or i in material_options):
                    linked_seed = (value, raw, link, span)
            vector.append(bucket)
            # An equality-filtered column denotes one query condition; retain
            # all original cell surfaces under that condition and identity.
            signature.append(() if material_options and columns[i] in equal_fields and i not in material_options
                             else tuple(sorted(bucket, key=lambda v: (v is not None, v or ""))))
        key = tuple(signature)
        if key in membership_keys:
            continue
        membership_keys.add(key)
        if key in groups:
            group = groups[key]
            for prior, current in zip(group["cells"], vector):
                for raw, labels in current.items():
                    prior.setdefault(raw, set()).update(labels)
            group["count"] += 1
            continue
        value = linked_seed[0] if linked_seed is not None else representative
        seed = None
        if value is not None:
            seed = {k: record[k] for k in ("kind", "permission_scope", "source_observation_id", "source_hash")}
            seed["values"] = [value]
            seed["span"] = linked_seed[3] if linked_seed is not None else value["evidence_spans"][0]
            if linked_seed is not None:
                seed["link_raw"], seed["link"] = linked_seed[1:3]
        groups[key] = {"cells": vector, "count": 1, "seed": seed}


def _group_anchor(index, group, revision, sealed, budget):
    """Bind the representative to the immutable original, including context-only edges."""
    record = group.pop("seed")
    if record is None:
        return None
    value, span = record["values"][0], record["span"]
    if record["kind"] == "table_row":
        fields = _native_fields(record, revision, budget)
    else:
        original = sealed[value["export_row_id"]]
        fields = [(prop, fact) for prop, facts in original["fields"].items() for fact in facts]
        if record.get("link") == "quote_mention":
            fields.extend((None, {"permission_scope": fact["permission_scope"],
                                  "permission_scope_fingerprint": fact["permission_scope_fingerprint"],
                                  "evidence_spans": t["evidence_spans"]})
                          for _, fact in tuple(fields) for t in fact.get("times", ()) if t.get("evidence_spans"))
            fields.extend((None, fact) for fact in (original.get("subject_identity") or {}).get("sources", ()))
    for prop, fact in fields:
        if fact["permission_scope"]["scope_id"] != record["permission_scope"]:
            continue
        if record.get("link") != "quote_mention":
            if (prop != value["property_id"] or fact.get("raw_property") != value["column_name_raw"]
                    or (None if fact["value"] is None else str(fact["value"])) != value["raw_value"]):
                continue
        for sealed_span in fact["evidence_spans"]:
            if sealed_span["observation_hash"] != span["observation_hash"]:
                continue
            if record.get("link") == "quote_mention" and record["link_raw"] not in sealed_span["quote"].split():
                continue
            if record["kind"] != "table_row" and sealed_span != span:
                continue
            field = {**fact, "evidence_spans": [sealed_span],
                     "observation_hashes": {sealed_span["observation_id"]: sealed_span["observation_hash"]}}
            return {"row_id": ("result_group", index), "fields": {"_link_proof": [field]}}
    raise ValueError("record result representative changed")


def _convert_records(records, revision, plan, budget, groups=None):
    from formowl_records.store import range_bounds
    bounds = range_bounds(plan["filters"])
    ids = {rid for record in records for rid in record["export_row_ids"]}
    for group in groups or ():
        seed = group["seed"]
        if seed and seed["kind"] != "table_row":
            ids.add(seed["values"][0]["export_row_id"])
    try:
        sealed = revision.candidate_fact_rows.read_selected(sorted(ids), budget["deadline"])
    except (TimeoutError, KeyError, ContractValidationError):
        sealed = {}
    seeds = [g["seed"] for g in groups or () if g["seed"]]
    from itertools import zip_longest
    native = [r for pair in zip_longest(seeds, records) for r in pair if r and r["kind"]=="table_row"]
    batch_deadline = budget["deadline"] - .65
    max_rows = _RECORD_PROOF_PAGE
    # With little hydration time left, spend it on the three reserved rows.
    # A smaller shard request avoids preparing a full page before the first hit.
    if batch_deadline - time.monotonic() < .15:
        max_rows = 3
        batch_deadline = budget["deadline"] - .45
    row_hashes = set(list(dict.fromkeys(r["source_hash"] for r in native))[:max_rows])
    nominated = [r for r in native if r["source_hash"] in row_hashes]
    wanted = {*plan["return"], *(f["property"] for f in plan["filters"])}
    refs = [r["span"]["observation_hash"] for r in seeds if r["kind"]=="table_row"]
    for r in records:
        if r["source_hash"] in row_hashes:
            refs.extend(v["citation_hash"] for v in r["values"] if v["property_id"] in wanted
                        or "column:"+str(v["column_name_raw"]) in wanted
                        or any(v["column_name_raw"] in names for names in plan.get("column_variants", {}).values()))
            refs.extend(e["citation_hash"] for e in r["entities"])
    try:
        verified = _native_batch(nominated, budget, deadline=batch_deadline, stage=True, priority_refs=refs)
    except ContractValidationError:
        verified = {}
    for record in native:
        record["_source_members"] = verified.get(record["source_hash"], {})
    for i, group in enumerate(groups or ()):
        if time.monotonic() >= budget["deadline"] or not group["seed"]:
            continue
        try:
            anchor = _group_anchor(i, group, revision, sealed, budget)
            if anchor:
                field = anchor["fields"]["_link_proof"][0]
                group["detail_field"] = field
                group["detail_span"] = field["evidence_spans"][0]
        except (KeyError, ValueError, ContractValidationError):
            continue
    rows = []
    for record in records:
        if time.monotonic() >= budget["deadline"]:
            break
        try:
            candidate = _candidate(record, revision, plan, budget, sealed, bounds)
        except (KeyError, ValueError, ContractValidationError):
            continue
        if candidate is not None:
            proofs = candidate["fields"]["_link_proof"]
            for group in groups or ():
                field = group.pop("detail_field",None) if group["representative"] == record["record_id"] else None
                if field is not None and field not in proofs:
                    proofs.append(field)
            rows.append(candidate)
    return rows


def _in_family(record, revision, families, selector, budget, cache):
    if record["kind"] == "table_row":
        members = _native_batch([record], budget, require_complete=True).get(record["source_hash"])
        if members:
            record["_source_members"] = members
        return bool(members)
    reader = revision.source_records
    # Grouping can join multiple export members. Scope every member before counting.
    for value in record["values"]:
        for span in (*value["evidence_spans"], *value["context_spans"]):
            digest = span["observation_hash"]
            key = (span["observation_id"], digest, record["permission_scope"])
            if key not in cache:
                helper, authority = reader._helper(span["observation_id"])
                if helper["observation_hash"] != digest or helper["source_scope_id"] != record["permission_scope"]:
                    return False
                family = helper.get("retrieval_source_family")
                if family is None:
                    if budget["reads"] >= budget["max_reads"] or time.monotonic() >= budget["deadline"]:
                        raise TimeoutError
                    budget["reads"] += 1
                    family = _semantic_observation_retrieval_source_family(reader.get_observation(span["observation_id"]))
                cache[key] = family, _authorized_mail_selector_for_asset(authority.asset)
            family, owner = cache[key]
            if family not in families or selector is not None and owner != selector:
                return False
    return True


def query_records(revision, table_query, contract, capabilities, selector, budget, max_reads, *, exact_lookup=None, required_terms=None):
    import psycopg
    from formowl_records.store import execute, range_bounds
    budget.update(max_reads=max_reads, exact_lookup=exact_lookup, record_families=contract["source_family_scope"],
                  record_selector=selector)
    budget["record_lookup_reason"] = "not_requested"
    budget["record_lookup_queried"] = False
    budget.pop("record_identifier_lookup", None)
    budget.pop("record_timeout_text_anchor", None)
    if table_query is None and required_terms is None:
        return [], None
    if required_terms is not None and (not isinstance(required_terms, tuple) or not 1 <= len(required_terms) <= 8
            or any(not isinstance(term, str) or not term.strip() or len(term) > 80 for term in required_terms)):
        budget["record_lookup_reason"] = "validation_error"
        raise ContractValidationError("invalid record lookup terms")
    server_fields = {**capabilities["record_table_fields"], "properties": {}}
    # Runtime source-derived vocabulary requires the configured private mount.
    # The planner can also accept explicitly supplied capabilities on its own.
    if _private_aliases() is not None:
        server_fields["properties"] = {
            prop: list(labels) for prop, labels in capabilities["record_table_fields"].get("properties", {}).items()}
        for label, prop in getattr(getattr(revision, "candidate_fact_rows", None), "aliases", ()):
            if _safe_field_alias(label):
                server_fields["properties"].setdefault(prop, []).append(label)
    try:
        plan = (plan_for(table_query, server_fields, contract["requested_fields"])
                if table_query is not None else None)
    except ContractValidationError:
        budget["record_lookup_reason"] = "validation_error"
        raise
    try:
        scopes = list(revision.authorized_source.source_scope_ids)
        pin = revision.safe_binding["source_revision_sha256"]
        families = contract["source_family_scope"]
        restricted = selector is not None or set(families) != set(capabilities["source_families"])
        scope_cache = {}
        def admit(record):
            if time.monotonic() >= budget["deadline"]:
                raise TimeoutError("record source permission deadline")
            return _in_family(record, revision, families, selector, budget, scope_cache)

        with _connection(budget["deadline"]) as db:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            db.execute("SET LOCAL jit=off")
            budget["record_lookup_queried"] = True
            native_families = families if restricted and selector is None else None
            if plan is None:
                plan, reason = _automatic_plan(required_terms, server_fields,
                    contract["requested_fields"], scopes, pin, db, admit=admit if restricted else None,
                    native_families=native_families)
                if plan is None:
                    budget["record_lookup_reason"] = reason
                    return [], None
            fact_columns = None
            if any(label.startswith("column:") for label in [*plan["return"], *(f["property"] for f in plan["filters"])]):
                fact_column_names = getattr(revision.candidate_fact_rows, "raw_column_names", None)
                if callable(fact_column_names):
                    fact_columns = fact_column_names()
            plan = _resolve_raw_plan(plan, scopes, pin, db, admit=admit if restricted else None,
                native_families=native_families, deadline=budget["deadline"],
                fact_columns=fact_columns)
            bounds = range_bounds(plan["filters"])
            equal_fields = {f["property"] for f in plan["filters"] if f["op"] == "eq"}
            page = execute({**plan,"limit":_RECORD_PROOF_PAGE}, scopes, connection=db, _result_groups=True, _admit=admit if restricted else None,
                           _restricted=restricted, source_revision_sha256=pin, _deadline=budget["deadline"],
                           _native_source_families=native_families, _summary_source_families=families,
                           _summary_selector=selector, _require_unresolved_summary=True)
            counts = {key:page[key] for key in ("total","without_projection","quantity_only","unresolved_value_count", "unresolved_value_count_status", "unresolved_value_count_reason")
                      if key in page}
            selected = [r for r in page["rows"] if r["projection_hits"]]
            representatives = {r["record_id"]:r for r in selected}
            result_groups = []
            summaries = page["result_groups"]
            projection_cache = {}
            for index, (signature, count, rid, variants, proved) in enumerate(summaries):
                if proved is False:
                    raise ValueError("record result group missing identity proof")
                cells = [{} for _ in plan["return"]]
                for vector in variants:
                    for bucket, labels in zip(cells, vector, strict=True):
                        for raw, name, via, normalized in labels:
                            if any(isinstance(v,str) and redact_public_raw_references(v)[1] for v in (raw,name,normalized)):
                                raise ValueError("unavailable public result value")
                            bucket.setdefault(raw,set()).add((name,via,normalized))
                group = {"cells":cells,"count":count,"seed":None,"representative":rid}
                if rid in representatives:
                    if rid not in projection_cache:
                        projected = {}
                        _collect_result_group(projected,representatives[rid],plan["return"],bounds,equal_fields)
                        projection_cache[rid] = projected
                    source = projection_cache[rid][tuple(tuple(v) for v in signature)]
                    group["seed"] = source["seed"]
                result_groups.append(group)
        rows = _convert_records(selected, revision, plan, budget, result_groups)
        counts["export_revision"] = pin
        counts["groups"] = result_groups
        counts["columns"] = plan["return"]
        budget["record_lookup_reason"] = "matched" if counts["total"] else "no_matches"
        if not counts["total"] and not rows and not result_groups and len(plan["filters"]) == 1 and required_terms:
            from formowl_records.normalize import normalize
            from formowl_records.store import ENTITY_TYPES
            predicate = plan["filters"][0]
            if predicate["property"] in ENTITY_TYPES and predicate["op"] == "eq" and len(predicate["values"]) == 1:
                value = normalize("identifier", predicate["values"][0])["norm"]
                if value and value in {normalize("identifier", term)["norm"] for term in required_terms}:
                    budget["record_identifier_lookup"] = "no_matches"
        return rows, counts
    except (OSError, psycopg.Error, KeyError, ValueError, ContractValidationError, TimeoutError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "unavailable raw column":
            budget["record_lookup_reason"] = "validation_error"
            raise RecordFieldValidationError(server_fields) from None
        budget["record_lookup_unavailable"] = True
        budget["record_lookup_reason"] = "lookup_timeout" if isinstance(exc, (TimeoutError, psycopg.errors.QueryCanceled)) else "record_store_unavailable"
        if (budget["record_lookup_reason"] == "lookup_timeout" and table_query is not None
                and plan and len(plan["filters"]) == 1 and required_terms):
            from formowl_records.normalize import normalize
            from formowl_records.store import ENTITY_TYPES
            predicate = plan["filters"][0]
            if predicate["property"] in ENTITY_TYPES and predicate["op"] == "eq":
                anchor = normalize("identifier", predicate["values"][0])["norm"]
                budget["record_timeout_text_anchor"] = bool(anchor and any(
                    normalize("identifier", term)["norm"] == anchor for term in required_terms))
        _LOG.warning("record_table_lookup_unavailable reason=%s", type(exc).__name__)
        return [], None
