"""Bridge the local, permission-scoped record store to sealed candidate source verification."""
from collections import defaultdict
from pathlib import Path
import logging
import time
import unicodedata

from formowl_contract import ContractValidationError, redact_public_raw_references, sha256_json, to_plain
from formowl_mail.hybrid import _semantic_observation_retrieval_source_family
from formowl_mail.issue56_sealed_source import _authorized_mail_selector_for_asset

_SECRET = Path("/run/secrets/formowl-record-reader")
_LOG = logging.getLogger(__name__)
_RECORD_PROOF_PAGE = 20


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
                AND length(v.column_name_raw) BETWEEN 1 AND 120 ORDER BY 1 LIMIT 129""",
                (list(revision.authorized_source.source_scope_ids),)).fetchall()
    except (OSError, psycopg.Error):
        _LOG.warning("record_table_catalog_unavailable")
        rows = []
    props = {prop: [] for prop in PROPERTY_TYPES}
    for label, prop in revision.candidate_fact_rows.aliases:
        if prop in props and label != prop and len(label) <= 120 and not redact_public_raw_references(label)[1]:
            props[prop].append(label)
    return {"properties": props, "raw_columns": [s for s, in rows[:128] if not redact_public_raw_references(s)[1]],
            "raw_column_listing_truncated": len(rows) > 128}


def _fold(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def plan_for(query, capabilities, requested):
    from formowl_mail.human_uat_orchestrator import _validate_table_query
    from formowl_records.store import range_bounds
    _validate_table_query(query)
    aliases = defaultdict(set)
    for prop, labels in capabilities["properties"].items():
        for label in [prop, *labels]:
            aliases[_fold(label)].add(prop)

    def resolve(label):
        if len(label) > 120 or redact_public_raw_references(label)[1]:
            raise ValueError("invalid column")
        matches = aliases.get(_fold(label))
        if matches:
            if len(matches) != 1:
                raise ValueError("ambiguous alias")
            return next(iter(matches))
        # execute verifies the existence of every raw column in the authorized scope.
        return label if label.startswith("column:") else "column:" + label

    projections = [resolve(label) for label in query["projection_fields"]]
    if len(set(projections)) != len(projections) or any(resolve(label) not in projections for label in requested):
        raise ValueError("projection mismatch")
    predicates = []
    for item in query["filters"]:
        if len(item["value"]) > 400:
            raise ValueError("invalid value")
        predicates.append({"property": resolve(item["field"]), "op": item.get("op", "eq"), "values": [item["value"]]})
    try:
        range_bounds(predicates)
    except ValueError as exc:
        raise ContractValidationError(str(exc)) from None
    return {"filters": predicates, "return": projections, "limit": 128, "order_by": "projection_coverage"}


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
        fields.append((value["property_id"], dict(raw_property=label, value=raw, permission_scope=scope,
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
        for rid in record["export_row_ids"]:
            original = sealed.pop(rid)
            for prop, facts in original["fields"].items():
                for fact in facts:
                    all_fields.append((prop, fact))
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
        for key in (prop, "column:" + str(fact.get("raw_property"))):
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
        target = normalize(value_type, predicate["values"][0])["norm"]
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


def _record_identity_links(record, kind):
    """Resolve each stored edge to the same record's field or exact quote token."""
    from formowl_records.normalize import normalize
    from formowl_records.store import _identity_keys
    linked = {}
    for entity in record.get("entities", ()):
        if entity["entity_type"] != kind:
            continue
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
    projected, link_cache, material_options = [], {}, {}
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
            own = [cell for cell in cells if isinstance(cell[0], str) and cell[0].strip()]
            if own:
                cells = own
            else:
                if kind not in link_cache:
                    link_cache[kind] = _record_identity_links(record, kind)
                if link_cache[kind]:
                    cells = list(link_cache[kind].values())
                elif kind == "part":
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
                        or "column:"+str(v["column_name_raw"]) in wanted)
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


def query_records(revision, table_query, contract, capabilities, selector, budget, max_reads, *, exact_lookup=None):
    import psycopg
    from formowl_records.store import execute, range_bounds
    budget.update(max_reads=max_reads, exact_lookup=exact_lookup, record_families=contract["source_family_scope"],
                  record_selector=selector)
    try:
        plan = plan_for(table_query, capabilities["record_table_fields"], contract["requested_fields"])
    except ContractValidationError:
        raise
    except ValueError:
        return [], None
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

        bounds = range_bounds(plan["filters"])
        equal_fields = {f["property"] for f in plan["filters"] if f["op"] == "eq"}
        with _connection(budget["deadline"]) as db:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            db.execute("SET LOCAL jit=off")
            page = execute({**plan,"limit":_RECORD_PROOF_PAGE}, scopes, connection=db, _result_groups=True, _admit=admit if restricted else None,
                           _restricted=restricted, source_revision_sha256=pin, _deadline=budget["deadline"])
            counts = {key:page[key] for key in ("total","without_projection","quantity_only","unresolved_value_count")
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
                        for raw, name, via in labels:
                            if any(isinstance(v,str) and redact_public_raw_references(v)[1] for v in (raw,name)):
                                raise ValueError("unavailable public result value")
                            bucket.setdefault(raw,set()).add((name,via))
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
        return rows, counts
    except (OSError, psycopg.Error, KeyError, ValueError, ContractValidationError) as exc:
        budget["record_lookup_unavailable"] = True
        _LOG.warning("record_table_lookup_unavailable reason=%s", type(exc).__name__)
        return [], None
