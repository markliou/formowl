#!/usr/bin/env python3
"""Run the temporary FormOwl mail upload and evidence human-UAT web surface."""

from __future__ import annotations

import argparse
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))


def _install_document_first_package_namespace() -> None:
    """Expose actual mail submodules without executing the legacy package init."""

    package_name = "formowl_mail"
    package_root = PYTHON_ROOT / package_name
    existing = sys.modules.get(package_name)
    if existing is not None:
        existing_paths = tuple(Path(path) for path in getattr(existing, "__path__", ()))
        legacy_modules = (
            "formowl_mail.bundle",
            "formowl_mail.evidence",
            "formowl_mail.human_uat_upload",
            "formowl_mail.query",
        )
        if (
            getattr(existing, "__file__", None) is not None
            or package_root not in existing_paths
            or any(module_name in sys.modules for module_name in legacy_modules)
        ):
            raise RuntimeError("document-first FormOwl package namespace is unavailable")
        return
    spec = ModuleSpec(package_name, loader=None, is_package=True)
    spec.submodule_search_locations = [str(package_root)]
    package = module_from_spec(spec)
    package.__path__ = [str(package_root)]
    package.__all__ = []
    sys.modules[package_name] = package


def _load_document_first_dependencies() -> SimpleNamespace:
    """Load only the one-sidecar document-first runtime after CLI selection."""

    _install_document_first_package_namespace()
    from formowl_mail.human_uat_http import (
        MailHumanUatHttpConfig,
        MailHumanUatService,
        create_mail_human_uat_http_server,
    )
    from formowl_mail.human_uat_orchestrator import (
        CodexAppServerConversationModel,
        CodexAppServerStdioTransport,
        build_codex_app_server_proxy_command,
    )

    return SimpleNamespace(
        CodexAppServerConversationModel=CodexAppServerConversationModel,
        CodexAppServerStdioTransport=CodexAppServerStdioTransport,
        MailHumanUatHttpConfig=MailHumanUatHttpConfig,
        MailHumanUatService=MailHumanUatService,
        build_codex_app_server_proxy_command=build_codex_app_server_proxy_command,
        create_mail_human_uat_http_server=create_mail_human_uat_http_server,
    )


def _load_legacy_dependencies() -> SimpleNamespace:
    """Load the PST/query/ontology runtime only for the legacy UAT mode."""

    from formowl_evaluator import load_or_rebuild_may_mail_evidence_bundle
    from formowl_mail.human_uat_http import (
        MailHumanUatHttpConfig,
        MailHumanUatService,
        create_mail_human_uat_http_server,
    )
    from formowl_mail.human_uat_orchestrator import (
        CodexAppServerConversationModel,
        CodexAppServerStdioTransport,
        build_codex_app_server_proxy_command,
    )
    from formowl_mail.query import MailEvidenceQueryGateway

    try:
        from formowl_mail.human_uat_orchestrator import load_semantic_ontology_context
    except ImportError:  # pragma: no cover - an older sidecar seam.
        load_semantic_ontology_context = None

    return SimpleNamespace(
        CodexAppServerConversationModel=CodexAppServerConversationModel,
        CodexAppServerStdioTransport=CodexAppServerStdioTransport,
        MailEvidenceQueryGateway=MailEvidenceQueryGateway,
        MailHumanUatHttpConfig=MailHumanUatHttpConfig,
        MailHumanUatService=MailHumanUatService,
        build_codex_app_server_proxy_command=build_codex_app_server_proxy_command,
        create_mail_human_uat_http_server=create_mail_human_uat_http_server,
        load_or_rebuild_may_mail_evidence_bundle=load_or_rebuild_may_mail_evidence_bundle,
        load_semantic_ontology_context=load_semantic_ontology_context,
    )


def _absolute_path(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return path.absolute()


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _require_disjoint_paths(
    paths: Iterable[tuple[str, Path]],
    *,
    label: str,
) -> None:
    normalized = tuple((name, _absolute_path(path, f"{label} {name}")) for name, path in paths)
    for index, (first_name, first_path) in enumerate(normalized):
        for second_name, second_path in normalized[index + 1 :]:
            if _paths_overlap(first_path, second_path):
                raise ValueError(f"{label} {first_name} and {second_name} must not overlap")


def _validate_dual_runtime_isolation(
    args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path]:
    """Validate the deployment's two independent app-server boundaries."""

    private_state = _absolute_path(
        args.private_codex_runtime_state_dir,
        "private Codex runtime state directory",
    )
    web_state = _absolute_path(
        args.web_codex_runtime_state_dir,
        "web Codex runtime state directory",
    )
    private_socket = _absolute_path(
        args.private_codex_socket,
        "private Codex socket path",
    )
    web_socket = _absolute_path(args.web_codex_socket, "web Codex socket path")
    http_state = _absolute_path(args.state_dir, "UAT state directory")
    corpus_root = _absolute_path(args.corpus_root, "corpus root")
    bundle_cache = _absolute_path(args.bundle_cache, "bundle cache")
    private_manifest = _absolute_path(args.private_manifest, "private manifest")

    _require_disjoint_paths(
        (
            ("private runtime state", private_state),
            ("web runtime state", web_state),
            ("UAT state", http_state),
        ),
        label="Codex runtime isolation",
    )
    if private_socket == web_socket:
        raise ValueError("private and web Codex socket paths must differ")

    # The web-capable sidecar must never be configured underneath a local
    # evidence, cache, transcript, or private-sidecar state path.
    for protected_name, protected_path in (
        ("corpus root", corpus_root),
        ("bundle cache", bundle_cache),
        ("private manifest", private_manifest),
        ("UAT state", http_state),
        ("private runtime state", private_state),
    ):
        if _paths_overlap(web_state, protected_path):
            raise ValueError("web Codex runtime state must not overlap " f"{protected_name}")

    private_workspace = private_state / "codex-workspace"
    web_workspace = web_state / "codex-workspace"
    private_proxy_home = http_state / "codex-proxy-home"
    private_proxy_workspace = http_state / "codex-proxy-workspace"
    web_proxy_home = web_state / "web-codex-proxy-home"
    web_proxy_workspace = web_state / "web-codex-proxy-workspace"
    _require_disjoint_paths(
        (
            ("private runtime workspace", private_workspace),
            ("web runtime workspace", web_workspace),
        ),
        label="Codex runtime isolation",
    )
    for web_path_name, web_path in (
        ("web Codex runtime state", web_state),
        ("web Codex runtime workspace", web_workspace),
        ("web Codex proxy home", web_proxy_home),
        ("web Codex proxy workspace", web_proxy_workspace),
    ):
        for protected_name, protected_path in (
            ("corpus root", corpus_root),
            ("bundle cache", bundle_cache),
            ("private manifest", private_manifest),
            ("UAT state", http_state),
            ("private runtime state", private_state),
            ("private runtime workspace", private_workspace),
            ("private Codex proxy home", private_proxy_home),
            ("private Codex proxy workspace", private_proxy_workspace),
        ):
            if _paths_overlap(web_path, protected_path):
                raise ValueError(f"{web_path_name} must not overlap {protected_name}")
    return private_workspace, web_workspace, web_proxy_home, web_proxy_workspace


def _require_semantic_dual_runtime_api(dependencies: SimpleNamespace) -> None:
    """Reject an older single-sidecar seam before it can process UAT data."""

    if not callable(dependencies.load_semantic_ontology_context):
        raise RuntimeError(
            "semantic dual-runtime API is unavailable; "
            "refuse to start the legacy single-sidecar UAT"
        )
    import inspect

    required_parameters = {"ontology_context", "web_grounding_transport"}
    try:
        signature = inspect.signature(dependencies.CodexAppServerConversationModel)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("semantic dual-runtime API is unavailable") from exc
    if not required_parameters.issubset(signature.parameters):
        raise RuntimeError(
            "semantic dual-runtime API is unavailable; "
            "refuse to start the legacy single-sidecar UAT"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--document-first", action="store_true")
    parser.add_argument("--document-mcp-url")
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--private-manifest", type=Path)
    parser.add_argument("--bundle-cache", type=Path)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument(
        "--private-codex-socket",
        type=Path,
        required=True,
        help="Unix socket for the no-web private semantic planner.",
    )
    parser.add_argument(
        "--web-codex-socket",
        type=Path,
        help="Unix socket for the separate public web terminology grounder.",
    )
    parser.add_argument(
        "--private-codex-runtime-state-dir",
        type=Path,
        required=True,
        help="Absolute state root mounted only into the private sidecar.",
    )
    parser.add_argument(
        "--web-codex-runtime-state-dir",
        type=Path,
        help="Absolute state root mounted only into the web-only sidecar.",
    )
    parser.add_argument(
        "--semantic-ontology",
        type=Path,
        help="Absolute public, versioned semantic ontology JSON.",
    )
    parser.add_argument(
        "--diagnostic-mcp-url",
        help=(
            "Explicit HTTP endpoint for the separate FormOwl diagnostic MCP "
            "(for example, its /mcp route)."
        ),
    )
    parser.add_argument("--index-workers", type=int, default=1)
    args = parser.parse_args()

    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")
    if args.index_workers < 1 or args.index_workers > 4:
        parser.error("--index-workers must be between 1 and 4")
    if args.document_first:
        if not args.document_mcp_url:
            parser.error("--document-mcp-url is required with --document-first")
        try:
            private_state = _absolute_path(
                args.private_codex_runtime_state_dir,
                "private Codex runtime state directory",
            )
            private_socket = _absolute_path(
                args.private_codex_socket,
                "private Codex socket path",
            )
            http_state = _absolute_path(args.state_dir, "UAT state directory")
            _require_disjoint_paths(
                (
                    ("private runtime state", private_state),
                    ("UAT state", http_state),
                ),
                label="Codex runtime isolation",
            )
        except ValueError as exc:
            parser.error(str(exc))
        dependencies = _load_document_first_dependencies()
        runtime_workspace = private_state / "codex-workspace"
        proxy_home = http_state / "codex-proxy-home"
        proxy_workspace = http_state / "codex-proxy-workspace"
        transport = dependencies.CodexAppServerStdioTransport(
            command=dependencies.build_codex_app_server_proxy_command(
                socket_path=private_socket,
            ),
            cwd=proxy_workspace,
            codex_home=proxy_home,
            runtime_workspace=runtime_workspace,
            allow_public_web_search=False,
        )
        conversation_model = dependencies.CodexAppServerConversationModel(
            transport,
            workspace_dir=runtime_workspace,
            model=os.environ.get("FORMOWL_UAT_CODEX_MODEL", "").strip() or None,
            reasoning_effort=os.environ.get(
                "FORMOWL_UAT_CODEX_REASONING_EFFORT",
                "low",
            ),
        )
        try:
            service = dependencies.MailHumanUatService(
                dependencies.MailHumanUatHttpConfig(
                    bundle=None,
                    state_dir=http_state,
                    conversation_model=conversation_model,
                    document_mcp_url=args.document_mcp_url,
                )
            )
            server = dependencies.create_mail_human_uat_http_server(
                args.host,
                args.port,
                service,
            )
            print(
                "FORMOWL_DOCUMENT_FIRST_UAT_READY "
                f"host={args.host} port={server.server_address[1]} "
                f"orchestrator_model={conversation_model.model_name} "
                "conversation_engine=codex_app_server "
                "mcp_calls_per_turn=1 document_first=true "
                "ontology=false public_search=false pst_parse=false",
                flush=True,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        finally:
            conversation_model.close()
        return 0
    for option_name in (
        "corpus_root",
        "private_manifest",
        "bundle_cache",
        "web_codex_socket",
        "web_codex_runtime_state_dir",
        "semantic_ontology",
        "diagnostic_mcp_url",
    ):
        if getattr(args, option_name) is None:
            parser.error(f"--{option_name.replace('_', '-')} is required")
    dependencies = _load_legacy_dependencies()
    try:
        _require_semantic_dual_runtime_api(dependencies)
        (
            private_runtime_workspace,
            web_runtime_workspace,
            web_proxy_home,
            web_proxy_workspace,
        ) = _validate_dual_runtime_isolation(args)
        ontology_context = dependencies.load_semantic_ontology_context(args.semantic_ontology)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))

    manifest = json.loads(args.private_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        parser.error("--private-manifest must contain a JSON object")
    bundle = dependencies.load_or_rebuild_may_mail_evidence_bundle(
        args.corpus_root,
        manifest,
        cache_path=args.bundle_cache,
    )
    base_gateway = dependencies.MailEvidenceQueryGateway(
        [bundle],
        index_worker_count=args.index_workers,
    )
    proxy_home = args.state_dir / "codex-proxy-home"
    proxy_workspace = args.state_dir / "codex-proxy-workspace"
    model_name = os.environ.get(
        "FORMOWL_UAT_CODEX_MODEL",
        os.environ.get("FORMOWL_UAT_MODEL", ""),
    ).strip()
    reasoning_effort = os.environ.get(
        "FORMOWL_UAT_CODEX_REASONING_EFFORT",
        os.environ.get("FORMOWL_UAT_REASONING_EFFORT", "low"),
    )
    transport = dependencies.CodexAppServerStdioTransport(
        command=dependencies.build_codex_app_server_proxy_command(
            socket_path=args.private_codex_socket,
        ),
        cwd=proxy_workspace,
        codex_home=proxy_home,
        runtime_workspace=private_runtime_workspace,
        allow_public_web_search=False,
    )
    web_grounding_transport = dependencies.CodexAppServerStdioTransport(
        command=dependencies.build_codex_app_server_proxy_command(
            socket_path=args.web_codex_socket,
        ),
        cwd=web_proxy_workspace,
        codex_home=web_proxy_home,
        runtime_workspace=web_runtime_workspace,
        allow_public_web_search=True,
    )
    conversation_model = dependencies.CodexAppServerConversationModel(
        transport,
        workspace_dir=private_runtime_workspace,
        model=model_name or None,
        reasoning_effort=reasoning_effort,
        ontology_context=ontology_context,
        web_grounding_transport=web_grounding_transport,
    )
    try:
        service = dependencies.MailHumanUatService(
            dependencies.MailHumanUatHttpConfig(
                bundle=bundle,
                state_dir=args.state_dir,
                conversation_model=conversation_model,
                diagnostic_mcp_url=args.diagnostic_mcp_url,
            ),
            base_gateway=base_gateway,
        )
        server = dependencies.create_mail_human_uat_http_server(
            args.host,
            args.port,
            service,
        )
        print(
            "FORMOWL_MAIL_UAT_READY "
            f"host={args.host} port={server.server_address[1]} "
            f"messages={len(bundle.messages)} upload_supported=true "
            f"orchestrator_model={conversation_model.model_name} "
            f"index_mode={base_gateway.index_build_mode} "
            f"index_workers={base_gateway.index_worker_count} "
            f"index_build_ms={base_gateway.index_build_elapsed_ms} "
            "conversation_engine=codex_app_server "
            "semantic_planning=private_no_web "
            "terminology_grounding=separate_public_web "
            "authentication_required=false shared_uat=true "
            "business_systems_read_only=true",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        conversation_model.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
