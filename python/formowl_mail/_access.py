from __future__ import annotations

from datetime import datetime
from typing import Sequence

from formowl_contract import ContractValidationError, Grant

from .bundle import MailEvidenceBundle


def matching_bundles(
    bundles: Sequence[MailEvidenceBundle],
    *,
    mail_import_session_id: str | None,
    mail_evidence_bundle_id: str | None,
) -> list[MailEvidenceBundle]:
    return [
        bundle
        for bundle in bundles
        if (
            mail_import_session_id is None
            or bundle.mail_import_session.mail_import_session_id == mail_import_session_id
        )
        and (
            mail_evidence_bundle_id is None
            or bundle.mail_evidence_bundle_id == mail_evidence_bundle_id
        )
    ]


def grant_expired(grant: Grant, now: str) -> bool:
    try:
        expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expires <= current


def normalize_grants(grants: Sequence[Grant | dict[str, object]]) -> list[Grant]:
    if isinstance(grants, (str, bytes)) or not isinstance(grants, Sequence):
        raise ContractValidationError("grants must be a list")
    return [grant if isinstance(grant, Grant) else Grant.from_dict(grant) for grant in grants]
