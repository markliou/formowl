# Issue #20 帳號系統檢查清單與驗證狀態

## 文件資訊與結論

- 日期：2026-07-21（更新至 689/689/689 repository authority）
- 對象：PM、產品負責人、後續實作者與驗收人員
- 範圍：Google OIDC、FormOwl OAuth 2.1、帳號映射、工作區身分、MCP 授權與稽核
- 狀態：Issue #20 仍為 open，不可宣稱完成、可關閉或 production ready

帳號系統已有相當完整的 repository-side 安全測試。Google 只驗證人，
FormOwl 自己核發 MCP access token；每次 protected MCP call 都重新讀取
使用者、membership、grant、token session 與 revocation，再建立新的
`ActorContext`。

目前不能上線的主因不是 repository-side onboarding 或本機 harness：

1. Current changed-function inventory、manifest 與 onboarding 已達
   689/689/689。Pending、missing、extra、duplicate、source-binding
   mismatch 與 validator blockers 全部為 0。
2. Final local whole-manifest execution 為 508/508/508/508
   requested／resolved／run／pass；共檢查 1,388 evidence pairs，
   direct trace expected／covered 689/689、missing 0、blockers `[]`，
   `test_id_count` 1,521。Skips、failures、errors、resolution／execution
   blockers 與 validator blockers 全部為 0。
3. Cross-UID failure-diagnostic custody 已改成 inner mode `0200` → `fsync` →
   `0444` ephemeral handoff，再由 outer 驗證後建立 runner-owned mode `0400`
   final diagnostic。Target harness／trace 為 25/25、33/33（51 pairs）；
   operator 與 runner modules 為 28/28、38/38。Full Ruff check／format、
   manifest JSON、runner `sh -n`、`git diff --check` 與 untracked text-style
   checks 通過；原 governance reviewer 已完成 finding-specific 1/1
   re-review 並回覆 `RELEASE_DECISION: AGREE`。Author 與純驗證 agent 不
   計入 reviewer；既有 connected-operator batch 3/3 reviewer evidence
   保持有效。
4. `_runtime_data_stores_ready()` 已移除 return-in-`finally`。既有
   `tests.test_connected_runtime.ConnectedRuntimeLifecycleTests.test_upload_store_readiness_probe_is_atomic_clean_and_fail_closed`
   明確驗證 descriptor-close fault 後仍嘗試 cleanup 且 readiness fail
   closed；focused runtime 為 36/36。
5. 上述 3/3 是 scoped repository reviewer gate，不是 Issue #20-wide
   reviewer layer。七個 required external layers 仍全部是
   `not_supplied`：`live_postgresql`、`operator_cli_postgresql`、
   `production_container_lifecycle`、`mcp_inspector`、
   `live_chatgpt_google`、`reviewer_gate`、`completion_audit`。
6. Clean-clone operator contract 現在有 tracked non-secret Compose env
   template、ignored operator copy workflow、Caddy TLS sample、discovery-only
   start/check/stop/finalize 順序、official public-only `npx` MCP Inspector 與
   container-first evidence commands。Implementation contract 明確綁定
   tracked `Caddyfile.example`、`compose.env.example`、operator config、
   secret guidance 與 signing-key example，不綁定 ignored operator-local
   Caddy/env copies；real BuildKit regression 證明 current source 與 frozen
   snapshot 的 implementation-contract hash 完全相等。這些是本機操作
   契約與回歸證據，不是 live external evidence。
   predefined client ID 必須由 operator 在 discovery 前以 containerized
   helper 產生或驗證並記錄；ChatGPT app management 僅顯示 callback，且
   必須能設定同一 predefined client ID，否則為 external live blocker。
   public domain/TLS、Google credentials/accounts 與所有 live campaign
   仍須外部 operator 提供；不可宣稱 ChatGPT 產生或顯示 client ID。
7. Finalization CLI 的 implementation-contract computation fault 現在只
   產生 generic failed validation，不洩漏 computation detail，也不以
   uncaught exception 離開；strengthened regression 與 onboarding
   manifest update 已納入 final harness。
8. Canonical full suite 精確結果為 `Ran 1521 tests in 964.613s`、
   `OK (skipped=7)`。Ruff check 通過；Ruff format check 回報 306 files
   already formatted；runner shell syntax、JSON parse 與 `git diff --check`
   通過。
9. Latest harness artifact 是
   `/tmp/formowl-issue20-postfix-local-harness-20260721T100124Z.json`，
   SHA-256
   `1adaeaf752148e730f421e0e385b0faa4a1aef4273d437def902bdb212e352b1`。
   Connector-confirmed GitHub current main 仍為
   `342e588aa6162ccbdd14a257bfc09e58e7a619ad`，沒有更新的 remote main；
   這只是 source baseline context，不是 external evidence。
10. 先前三個 read-only source reviewers 均認為 repository 可開始 fresh
   external campaign，但其 review 早於 final warning／snapshot cleanup，
   不構成 Issue-wide `reviewer_gate`。最後 reviewer packet 必須重新綁定
   frozen post-cleanup source。

目前可繼續內部開發與 controlled test，但不適合 production 交付。

## PM 快速檢查總表

| 檢查面向 | Repository-side 結果 | 尚缺項目 |
| --- | --- | --- |
| OAuth metadata、callback、PKCE、code/state/nonce | focused tests 通過 | 真實 public HTTPS 與 ChatGPT callback |
| clean-clone operator deployment contract | tracked non-secret env template、containerized safe client-ID helper、ignored env workflow、Caddy loopback proxy、discovery stop-before-migrate/preflight/bootstrap、official public-only `npx` Inspector flow | ChatGPT predefined-client entry/selection UI、displayed callback、domain/TLS、Google credentials、實際 operator execution；若 UI 無法設定同一 client ID 則為 external blocker |
| Google ID token 與 `(issuer, subject)` 帳號映射 | deterministic tests 通過 | 真實 Google owner／second-user journey |
| Invitation 與 first-owner bootstrap | atomic／idempotent／concurrency tests 通過 | fresh live PostgreSQL journey |
| FormOwl token、JWKS、resource binding、key rotation | focused／restart simulation 通過 | 兩次 production container lifecycle evidence |
| Fresh `ActorContext`、`whoami`、role/tool policy | focused remote tests 通過 | 真實 remote MCP Inspector 與 ChatGPT |
| `open_upload_session` owner／member／viewer policy | policy tests與 production-shaped E2E 通過；slice reviewer gate 3/3 AGREE | 真實 PostgreSQL／ChatGPT upload journey |
| revoke／remove／restore／relink | deterministic E2E 通過 | operator CLI 與 live ChatGPT relink evidence |
| transaction rollback、audit lineage、leak scan | focused tests 通過；coroutine 與 NaN／`+Inf`／`-Inf` audit-truthfulness slices 的 canonical `:ro` verification 與 scoped reviewer gates 均 3/3 AGREE | Issue #20-wide final reviewer gate |
| read-only wheel/package harness | `/tmp` staging、repo `:ro`、exact 1/1、module 15/15、Ruff、scoped reviewer 3/3 AGREE；production packaging 未改 | 不替代 production container external evidence |
| `ExternalIdentity.to_dict` serializer contract | exact ten-field payload、exact scalar runtime types、canonical verified email、no copy hooks／leak／mutation；exact 1/1、module 19/19、onboarding 1/1、trace 1/1、reviewer 3/3 AGREE | bounded function completion，不替代 Issue #20-wide evidence |
| exact `/mcp` → `open_upload_session` 22-function batch | remote 13、runtime 7、mail upload 2；無 production change；scoped validator 0 blockers／mismatches、exact 4/4、related 92/92、onboarding 26/26、target harness 21/21、trace 22/22／52 pairs、reviewers 3/3 AGREE | bounded batch gate；Issue #20-wide reviewer external layer 仍 `not_supplied` |
| `formowl_gateway.operator` 22-function batch | public token-session lookup 的 non-UTC normalization 與惡意 `utcoffset()`／`astimezone()` generic-no-side-effect regressions；exact 1/1、regressions 3/3、module 13/13、harness 12/12、trace 22/22／69 pairs、reviewers 3/3 AGREE；production 未改 | bounded batch gate；Issue #20-wide reviewer external layer 仍 `not_supplied` |
| connected startup/secret 25-function batch | `secret_init` 13、`container_entrypoint` 12；production close/rollback/final-ownership fixes 與 signing／staged-write regressions；exact 1/1、entrypoint 12/12、onboarding 1/1、harness 21/21、trace 25/25／53 pairs、reviewers 3/3 AGREE | bounded batch gate；Issue #20-wide reviewer external layer 仍 `not_supplied` |
| PostgreSQL migration／transaction 25-function batch | repository lifecycle 6、connection transaction/query 7、`oauth_migration_path` 1、graph migration 11；34 hygiene mappings；owner modules 32/32、onboarding 1/1、harness 9/9、trace 25/25／31 pairs、reviewers 3/3 AGREE；production 未改 | bounded repository-side batch；不等於 live PostgreSQL 或 Issue #20-wide reviewer evidence |
| PostgreSQL CRUD／row-mapping 33-function batch | transaction/code 6、invitation 3、identity/profile 8、membership/grant 7、client/token 7、row mapping 2；35 hygiene mappings；identity keyed/not-found/zero-side-effect 與 token revoked/expired preservation regressions；owner 22/22、onboarding 2/2、harness 12/12、trace 33/33／46 pairs、reviewers 3/3 AGREE；production 未改 | bounded repository-side batch；不等於 live PostgreSQL 或 Issue #20-wide reviewer evidence |
| runner boundary 10-new／1-refreshed batch | canonical runner inode pin、fd 9 restore／cleanup、五組 capability sets zero；exact 1/1、module 33/33、onboarding 1/1、harness 16/16／23 pairs、trace 11/11、reviewers 3/3 AGREE | bounded process-safety gate；不等於 external evidence 或 production readiness |
| runner private failure-diagnostic integration | inner runtime UID `10001` 以 exclusive mode `0200` 寫入、`fsync` 後改為 mode `0444` ephemeral handoff；outer 驗證 owner／mode／inode／no-follow／closed-schema 後建立 runner-owned mode `0400` final diagnostic；exact handoff regressions 6/6、operator 28/28、runner 38/38、target harness 25/25／51 pairs、trace 33/33；原 governance reviewer finding-specific re-review 1/1 AGREE，author／純驗證 agent 不計入 | bounded runner diagnostics；未執行 live campaign，不等於 external evidence、Issue closure 或 production readiness |
| evidence-packet 56-function batch | packet module 37/37、exact onboarding 1/1、harness 14/14、trace 56/56／69 pairs、target blockers／binding mismatches 0、reviewers 3/3 AGREE | bounded repository-side packet validation；不等於 accepted external evidence 或 production readiness |
| connected-runtime live-E2E 56-function batch | owner 84/84、exact onboarding／isolation 2/2、harness 59/59、trace 56/56／106 pairs、五個直接 negative regressions、reviewers 3/3 AGREE | bounded repository-side journey evidence；不等於 accepted external evidence 或 production readiness |
| `_invalid_token_challenge` independent onboarding | current owner module 85/85、onboarding/isolation 2/2、harness 60/60、trace 57/57／108 pairs、reviewers 3/3 AGREE | independent function evidence；不擴張 earlier 56-function batch claim |
| `_validate_external_layer_counts` onboarding | test-only；focused 3/3、one-function harness 2/2、trace 1/1 missing 0、related 41/41、target blockers 0、reviewers 3/3 AGREE | branch-deletion proof 已補；不等於 external evidence |
| `scripts.oauth_mcp_harness` 31-function batch | atomic output failure safety、hostile constructor fallbacks；harness 15/15、trace 31/31／52 pairs、related 44/44、onboarding 1/1、reviewers 3/3 AGREE | bounded batch evidence；不等於 external evidence 或 readiness |
| connected operator PostgreSQL journey 33-function current batch | 五組 capability sets 必須存在／valid hex／zero；audit exact workspace／target lineage 綁定動態 invitation IDs，cross-UID diagnostic handoff fail closed，public count/hash-only；onboarding 1/1、target harness 25/25、trace 33/33／51 pairs、0 target blockers／mismatches；既有 batch reviewer gate 維持 3/3，重新打開的 custody finding 已由原 governance reviewer 1/1 re-review AGREE | bounded repository-side operator journey；不等於 live external evidence、Issue completion 或 readiness |
| final runtime readiness cleanup | no return-in-`finally`；既有 descriptor-close regression 驗證 cleanup 與 fail-closed；focused runtime 36/36 | scoped repository evidence；不等於 Issue-wide `reviewer_gate` |
| implementation-contract deploy binding | tracked Caddy/env examples、operator config、secret guidance、signing-key example 被納入；ignored operator-local Caddy/env copies 排除；real BuildKit current-source／frozen-snapshot hash equality 通過 | local source-freeze integrity；不等於 external campaign |
| finalization computation-fault boundary | computation fault 轉為 generic failed validation；不洩漏 detail、不 uncaught escape；strengthened regression 與 onboarding manifest update 通過 | local fail-closed CLI evidence；不等於 closure |
| 全 functions onboarding | changed／manifested／onboarded 689/689/689；pending／missing／extra／duplicate／binding mismatch／validator blockers 皆 0；whole manifest requested／resolved／run／pass 508/508/508/508，1,388 pairs；direct trace 689/689、missing 0；`test_id_count` 1,521；execution blockers 0 | local repository evidence only；7/7 external layers `not_supplied` |
| Issue closure | 不支援 | `live_postgresql`、`operator_cli_postgresql`、`production_container_lifecycle`、`mcp_inspector`、`live_chatgpt_google`、Issue-wide `reviewer_gate`、`completion_audit` |

## 已驗證的身分邊界

```text
ChatGPT
  -> exact HTTPS /mcp
  -> FormOwl OAuth 2.1
  -> Google OIDC 驗證人
  -> FormOwl (issuer, subject) 身分映射
  -> FormOwl access token
  -> fresh ActorContext
  -> current-state tool authorization
```

- Google access token／ID token 不能直接當 FormOwl MCP bearer token。
- email 只用於 invitation；穩定帳號鍵是 `(issuer, subject)`。
- FormOwl 管理 user、membership、role、grant、client authorization、
  token session、revocation 與 audit。
- caller 不能指定 user、workspace、session、grant、storage、parser 或
  worker 身分。
- manual trusted identity 只限測試／本機相容，不得進 connected runtime。
- Issue #20 建立身分與 `ActorContext`；PST、mail 與一般檔案的 tenant／
  owner isolation 仍由 Issue #41 負責。

## 被檢查的完整帳號旅程

Repository-side harness 與 focused tests 所覆蓋的目標旅程是：

1. 受控 operator 對空 workspace 建立 first-owner bootstrap，不建立
   placeholder／fake user。
2. first owner 完成 Google OIDC；FormOwl 建立真實 user、external identity
   與 owner membership。
3. operator 以受控 lookup 取得 owner 的穩定 FormOwl `user_id`。
4. owner／operator 為第二位使用者建立 invitation。
5. 第二位使用者完成 Google OIDC，建立自己的 user、identity 與 member
   membership；不可只靠相同 email 接管另一個 subject。
6. 第二位使用者以 FormOwl bearer token 呼叫 exact `/mcp`，`whoami`
   僅回傳目前 authenticated user 與 workspace。
7. owner／member 可呼叫 `open_upload_session`；viewer、錯誤 workspace、
   forged identity／grant 一律拒絕。Production-shaped E2E 已使用與
   principal user／token session 綁定、selection method 為
   `google_oidc_oauth` 的真實 `SessionIdentity` 通過，且保留 governed
   UploadSession、單一 audit、跨 workspace denial 與 leak-safety 斷言。
8. revoke token 後，下一次 MCP call 立即失敗。
9. remove membership 時撤銷該 user／workspace 的既有 sessions。
10. restore membership 不復活舊 token；使用者必須重新完成 OAuth。
11. 同一 `(issuer, subject)` relink 回到同一 FormOwl user；跨 workspace、
    不同 subject、偽造 token 或移除後舊 session 都不能越權。

## 實際完成的檢查

### 1. OAuth metadata、routes 與 callback

- 驗證 protected-resource metadata、authorization-server metadata、JWKS、
  authorize、Google callback、token 與 exact `/mcp`。
- 正式 callback 只接受預先允許的 ChatGPT callback 格式。
- discovery-only sentinel 不得誤成 ready 或允許狀態寫入。
- production HTTPS 與 loopback-only 測試設定有明確分界。

證據：`tests/test_oauth_config_routes.py::OAuthConfigRouteTests.test_metadata_properties_and_starlette_routes_are_exact`、`tests/test_oauth_config_routes.py::OAuthConfigRouteTests.test_chatgpt_callback_shape_and_reserved_sentinel_matrix`、`tests/test_mcp_oauth_gateway.py::RemoteMcpHttpTests.test_initialize_and_tool_list_are_public_on_exact_mcp_path`。

### 2. Authorization Code、PKCE、state 與 nonce

- PKCE 只接受 S256；verifier 不符時須在 code consumption 前 fail closed。
- code 綁定 client、callback、resource、scope、transaction 且只能使用一次。
- state、nonce、code 與 transaction correlation 不可重播或換綁。
- callback 的 locked transaction 欄位被修改時不得留下 partial state。

證據：`tests/test_oauth_contracts_and_security.py::OAuthContractsAndSecurityTests.test_oauth_security_primitives_cover_rfc7636_and_secret_separation`、`tests/test_oauth_bridge_service.py::OAuthBridgeServiceTests.test_pkce_verifier_matrix_fails_closed_before_code_consumption`、`tests/test_oauth_postgres_repository.py::OAuthPostgresRepositoryTests.test_consume_authorization_code_is_single_use_bound_and_transactional`。

### 3. Google ID token 與穩定帳號映射

- 驗證 signature、issuer、audience、expiry、nonce 與 `email_verified`。
- Google access token 在上游驗證後丟棄，不進入 FormOwl token。
- 相同 `(issuer, subject)` 重連仍是同一 user；不同 subject 不可只靠
  email 接管帳號。
- account switching 必須有獨立 invitation 與 membership。

證據：`tests/test_oauth_tokens_google.py::OAuthTokenAndGoogleTests.test_google_oidc_success_uses_fixed_endpoints_and_discards_access_token`、`tests/test_oauth_tokens_google.py::OAuthTokenAndGoogleTests.test_google_oidc_rejects_signature_claim_nonce_and_verified_email_failures`、`tests/test_oauth_bridge_service.py::OAuthBridgeServiceTests.test_reconnect_same_subject_updates_profile_without_rebinding_user`、`tests/test_oauth_mcp_e2e.py::OAuthMcpEndToEndTests.test_account_switch_requires_independent_invitation_and_membership`。

### 4. Invitation 與 first-owner bootstrap

- 一般 invitation 需要有效 workspace owner。
- first-owner bootstrap 只允許受信任 operator，且不建立 fake user。
- 真實 Google login 才建立 user 與 owner membership。
- identical retry 冪等、衝突 fail closed，repository／audit failure rollback。
- 已有 bounded PostgreSQL concurrency test；required external PostgreSQL
  evidence gate 仍是 `not_supplied`。

證據：`tests/test_oauth_bridge_service.py::OAuthBridgeServiceTests.test_invitation_provisioning_requires_active_workspace_owner_and_is_atomic`、`tests/test_oauth_bridge_service.py::OAuthBridgeServiceTests.test_owner_bootstrap_is_atomic_idempotent_and_creates_no_fake_user`、`tests/test_oauth_owner_bootstrap_postgres_live.py::OAuthOwnerBootstrapPostgresLiveTests.test_concurrent_conflicting_bootstrap_has_exactly_one_winner`。

### 5. FormOwl token、JWKS 與 key rotation

- FormOwl token 使用 RS256、固定 3600 秒 lifetime、綁定 canonical
  resource 與 scope；validation clock skew 固定為 30 秒，不得為了 evidence
  縮短 lifetime 或移動 clock。
- token 不攜帶 Google token、workspace 或 caller-controlled authorization。
- 錯誤 resource、scope、signature、algorithm、expiry、temporal claim 均
  fail closed。
- JWKS 只公開 verification material；rotation overlap 只保留未過期 key。
- mounted signing-key rotation 可跨 restart overlap。

證據：`tests/test_oauth_tokens_google.py::OAuthTokenAndGoogleTests.test_formowl_rs256_token_has_resource_binding_and_no_workspace_or_google_claims`、`tests/test_oauth_tokens_google.py::OAuthTokenAndGoogleTests.test_jwks_rotation_keeps_only_unexpired_overlap_key`、`tests/test_connected_runtime.py::ConnectedRuntimeConfigTests.test_file_mounted_signing_key_rotation_survives_restart_overlap`。

### 6. Fresh per-call authorization 與 current tool policy

- 每次 protected call 都重新載入 token session、user、external identity、
  client authorization、membership 與 active grants。
- `whoami`：owner／member／viewer 可用。
- `open_upload_session`：只允許 owner／member。
- viewer Grant 不得升權；unknown tool／missing policy 一律 fail closed。
- identity、workspace、session、grant injection 在 handler 前拒絕。

證據：`tests/test_mcp_oauth_gateway.py::RemoteMcpHttpTests.test_valid_bearer_resolves_fresh_actor_context_for_every_tool_call`、`tests/test_mcp_oauth_gateway.py::RemoteMcpHttpTests.test_nested_session_identity_tampering_fails_closed_before_handler`、`tests/test_mcp_oauth_gateway.py::RemoteMcpHttpTests.test_closed_tool_policy_allows_only_declared_roles_without_grants`、`tests/test_mcp_oauth_gateway.py::RemoteMcpHttpTests.test_viewer_upload_grants_cannot_elevate_and_denial_is_audited`。

Production-shaped `open_upload_session` slice 另以真實 `OAuthPrincipal`、
`ActorContext`、`SessionIdentity`、`User` 與 `WorkspaceMember` contract
完成驗證。Canonical repository `:ro` 證據為 exact regression 1/1、
`test_connected_runtime.py` 34/34、`test_mcp_oauth_gateway.py` 45/45、
scoped remote-helper onboarding 1/1，以及 targeted Ruff check／format
通過。此 slice 的 engineering、authorization/governance 與
test/manifest reviewer gate 為 3/3 `RELEASE_DECISION: AGREE`；這是 scoped
slice gate，不是 Issue #20-wide final reviewer gate。

### 7. Revocation、disabled、membership removal 與 relink

- token revocation 立即反映到下一個 MCP call。
- disabled user／identity、revoked client authorization、removed membership
  均 fail closed。
- membership removal 撤銷相關 sessions；restore 不復活舊 session，必須
  重走 OAuth。
- self、workspace owner 與 operator revocation authority 分離。

證據：`tests/test_oauth_bridge_service.py::OAuthBridgeServiceTests.test_revoked_or_disabled_binding_and_removed_membership_fail_closed`、`tests/test_connected_operator_directory.py::ConnectedOperatorDirectoryTests.test_membership_removal_revokes_sessions_and_restore_keeps_them_revoked`、`tests/test_oauth_mcp_e2e.py::OAuthMcpEndToEndTests.test_remote_http_invited_user_reconnect_revocation_and_workspace_boundary`。

### 8. Transaction、audit 與 leak safety

- PostgreSQL query 使用 parameter binding；失敗不得留下 partial write。
- audit lineage 綁定 user、identity、client、token session、request、tool、
  workspace 與 grant。
- log／public report／error envelope 不得輸出 token、secret、email、OAuth
  query、raw path、SQL 或 backend detail。
- strict-JSON 的 nested tuple 與 non-string mapping key regression 已修復；
  focused／remote checks 通過，reviewer 回覆 `RELEASE_DECISION: AGREE`。
- stateful `Mapping`、nested coroutine、cycle 與 custom-awaitable hardening
  candidate 已實作；canonical `:ro` verification 為 focused 5/5、
  affected modules 82/82、scoped onboarding 1/1，Ruff 與相關 checks 亦通過。
  Coroutine-scoped fresh final 3-reviewer gate 亦已完成：engineering、
  manifest/onboarding、governance/safety reviewer 為 3/3 AGREE，沒有
  blocker。因此目前狀態是 **candidate-fixed／scoped gate complete**，
  不是尚未處理的 engineering defect；這仍不等同 Issue #20-wide final
  reviewer gate 或 final closure。
- production fix `_safe_handler_envelope` 現在會在 semantic success log
  寫入前拒絕 NaN、`+Inf` 與 `-Inf`；有限浮點數 `1.25` 仍維持 canonical
  success。兩個 regression 都經由真實 `TestClient`、bearer authentication、
  exact `POST /mcp`、JSON-RPC 與官方 MCP result serialization 驗證。
- NaN audit-truthfulness slice 的 canonical `:ro` 證據為 scoped 15/15、
  direct trace 1/1 且 missing trace 為 0、Ruff check／format、manifest JSON
  與 scoped diff checks 全部通過；engineering、manifest/onboarding 與
  governance/safety reviewer 為 3/3 `RELEASE_DECISION: AGREE`。這只關閉
  scoped finding，不是 Issue #20-wide final reviewer evidence。

證據：`tests/test_oauth_postgres_repository.py::OAuthPostgresRepositoryTests.test_repository_keeps_untrusted_values_parameterized_and_uses_row_locks`、`tests/test_oauth_mcp_e2e.py::OAuthMcpHarnessPrimitiveTests.test_audit_lineage_requires_every_identity_token_tool_and_upload_link`、`tests/test_oauth_mcp_e2e.py::OAuthMcpEndToEndTests.test_every_repository_write_and_audit_failure_rolls_back_byte_for_byte`、`tests/test_mcp_oauth_gateway.py::RemoteMcpRunnerTests.test_gateway_does_not_emit_sensitive_values_to_logs`。

NaN／non-finite 證據：`tests/test_mcp_oauth_gateway.py::RemoteMcpHttpTests.test_real_semantic_handler_finite_float_result_is_canonical_success`、`tests/test_mcp_oauth_gateway.py::RemoteMcpHttpTests.test_real_semantic_handler_non_finite_result_cannot_leave_false_success_log`。

### 9. Manual trusted／connected runtime 隔離

- connected runtime 必須使用 `oauth_google`，拒絕 manual actor selection
  與 caller-supplied identity environment。
- manual trusted、JSON-line、hand-built JSON-RPC、stdio 僅限測試／local
  compatibility。
- discovery-only mode 不得執行 bootstrap、operator mutation 或 protected
  tool success。

證據：`tests/test_mcp_oauth_gateway.py::RemoteMcpHttpTests.test_connected_factory_rejects_manual_identity_environment`、`tests/test_connected_runtime.py::ConnectedRuntimeLifecycleTests.test_discovery_only_blocks_operator_state_and_audited_lookup_entrypoints`。

### 10. Issue #20 implementation contract hash

- `formowl_evidence.issue20.issue20_implementation_contract_hash` 對相同
  required source set 產生 deterministic、格式有效的 SHA-256。
- Deploy source set 綁定 tracked
  `deploy/connected/Caddyfile.example`、
  `deploy/connected/compose.env.example`、
  `deploy/connected/operator_config.py`、
  `deploy/connected/secrets/README.md` 與
  `deploy/connected/signing-key-set.example.json`。Ignored operator-local
  Caddy/env copies 不屬於 implementation authority，也不影響 digest。
- 任一納入 contract 的 migration、runtime image、Compose、tracked
  deploy template/example 或 runner source drift 都會改變 digest。
- 任一 required glob 沒有檔案時，以固定
  `issue20_implementation_contract_missing` fail closed；錯誤不洩漏 root
  path 或缺少的檔名，且不修改或產生 partial fixture state。
- Real BuildKit regression 以目前 repository source 建立 frozen snapshot，
  再對兩者重新計算 implementation-contract hash；兩者必須完全相等。
  這是 current-source-vs-frozen-snapshot equality proof，不是只測
  ignore-pattern parser 的 synthetic assertion。

### 10A. Finalization computation-fault handling

- `scripts/oauth_mcp_harness.py` 的 Issue #20 finalization CLI 將
  implementation-contract computation fault 轉為固定 shape 的 generic
  failed validation；private exception、path、missing filename 或計算細節
  不進入 public artifact，也不以 uncaught exception 離開。
- Strengthened regression 覆蓋 finalization computation fault 的 fail-closed
  行為，並驗證既有 output 不被錯誤結果取代。相關 finalization function
  evidence 已同步更新 `tests/issue20_function_harness_manifest.json`。
- 這個修正只增加本機 finalization safety；七個 external layers 仍須
  各自提供 accepted evidence，且 closure／production claims 仍為 false。

### 11. Manual trusted `select_actor` audit atomicity

- Canonical pre-fix regression 證明：
  `ManualTrustedInternalAuthProvider.select_actor` 在 audit persistence
  failure 時會先替換 `_selected_context`，使 `whoami()` 錯誤顯示未完成
  audit 的新 actor。
- Production 修正只調整 commit ordering：先建立完整 `ActorContext`，
  成功持久化 `actor_selected` audit 後，才提交 `_selected_context`。
  Audit failure 現在保留先前 actor context，且 audit files
  byte-for-byte 不變；錯誤維持 generic、沒有 backend detail leakage。
- Repository `:ro` focused evidence 為 4/4：exact audit-failure regression、
  success/current-workspace path、expired/revoked access-state filtering、
  scoped onboarding assertion。Provider module 2/2、function-scoped
  execution 3/3、direct trace 1/1、0 missing／0 blockers，以及 targeted
  Ruff check／format-check、manifest JSON、`git diff --check` 均通過。
- Engineering、governance/safety、test-methodology reviewer gate 為 3/3
  `RELEASE_DECISION: AGREE`。兩個 reviewer blockers 已以精確 assertions
  關閉：一組驗證 `current_workspace_id`／`current_workspace_role`，另一組
  驗證 audit `session_id`／`target_type`／`target_id` lineage。
- 這是 tests/local-compatibility manual provider 的 bounded slice，不是
  connected ChatGPT identity path，也不支援 production-readiness claim。

### 12. `ExternalIdentity.to_dict` exact serializer contract

- `formowl_auth.models.ExternalIdentity.to_dict` 現在固定輸出 exact
  ten-field payload，不接受額外或替代欄位形狀。
- 九個 string fields 都要求 exact `str` runtime type 並拒絕 `str`
  subclasses；`email_verified` 要求 exact `bool`。惡意
  `__copy__`／`__deepcopy__` probes 不會被呼叫。
- Verified email 必須通過 `normalize_verified_email`，且輸入本身已等於
  canonical normalized form。Serializer fail closed，不會在輸出時靜默
  修正 whitespace 或大小寫。
- Malformed 或 whitespace/case-noncanonical email 都精確拋出
  `ContractValidationError("ExternalIdentity is invalid")`；錯誤不洩漏
  input，object state 也維持不變。
- 第一位 reviewer 指出 exact-runtime-type test proof 不足。Canonical
  pre-fix email regression 確實連續失敗兩次：malformed 與 noncanonical
  email 都曾被 serializer 輸出。
- Final repository `:ro` evidence：exact regression 1/1、contract module
  19/19、scoped onboarding 1/1、scoped validator 0 binding mismatches／0
  target blockers、one-function harness 1/1、direct trace 1/1 且 0
  missing／blockers、Ruff check／format-check、manifest JSON parse 與
  `git diff --check` 全部通過。
- Engineering、governance、manifest reviewer gate 為 3/3
  `RELEASE_DECISION: AGREE`。兩個 blockers 都由原 reviewer re-review
  後關閉。這是 bounded function completion，不是 Issue #20 completion
  或 production readiness。

### 13. Connected startup／secret 25-function batch

- 13 個 `formowl_gateway.secret_init` 與 12 個
  `formowl_gateway.container_entrypoint` functions 已 status-onboarded。
- Production fixes 關閉 `_read_secret` descriptor-close detail leakage、
  `main` final ownership failure 後的 false-success evidence，以及 secret
  quarantine rollback 自身失敗時的 partial-state／operator-entry 風險。
- Strengthened tests 精確固定 current／previous signing-key rewrite 順序與
  previous key `verify_until`，並以 table-driven subtests 注入 partial
  `os.write`、`os.fchown`、`os.fsync` 與 descriptor `os.close` failures；
  每項都驗證 empty staging、generic
  `container_secret_stage_failed`、private-detail redaction、descriptor
  cleanup 與 retry success。
- Repository `:ro` proof：exact regression 1/1、entrypoint module 12/12、
  scoped onboarding 1/1、validator 0 target blockers／0 binding mismatches、
  target harness 21/21、53 evidence pairs、direct trace 25/25 且 0 missing。
- Engineering、governance/safety、manifest/onboarding 三個 reviewer streams
  關閉 read-secret close leakage、main false-success evidence、quarantine
  rollback-failure evidence、signing `verify_until` assertion與 staged-secret
  write/fchown/fsync/close cleanup proof，最終 3/3
  `RELEASE_DECISION: AGREE`。這仍是 bounded batch gate，不是 Issue #20-wide
  reviewer external layer、external evidence 或 production readiness。

### 14. PostgreSQL migration／transaction 25-function batch

- 25 targets 已 status-onboarded：六個
  `PostgreSQLOAuthRepository` lifecycle functions、七個
  `PsycopgOAuthConnection` transaction/query functions、
  `oauth_migration_path`，以及 11 個
  `formowl_graph.storage.postgres` migration functions。
- 同一 bounded onboarding regression 也固定 34 個既有 N/A-reason
  hygiene mappings；後續 33 個 `formowl_auth.postgres`
  CRUD／row-mapping functions 的目前權威見下一節。
- Repository `:ro` evidence：三個 owner modules 32/32、scoped onboarding
  1/1、target harness 9/9、direct trace 25/25、0 missing／blockers、31
  checked evidence pairs，且 scoped validator 為 0 target blockers／0
  source-binding mismatches。
- Production code 未修改。唯一 test hardening 是
  `PostgreSQLOAuthRepository.apply_migrations` 在 migration 中途失敗時
  begin 一次、rollback 一次、commit 零次，捨棄 staged advisory-lock、
  ledger/schema 與 migration effects 並保留既有 durable state；以及
  `PostgreSQLMigrationResult.to_safe_dict` 的 fixed scalar safe-shape／
  leak boundary。
- Engineering、governance/safety、manifest/onboarding reviewers 為 3/3
  `RELEASE_DECISION: AGREE`，zero blockers。這仍不是 live PostgreSQL、
  external evidence、Issue #20 completion 或 production readiness。

### 15. PostgreSQL CRUD／row-mapping 33-function batch

- 33 targets 已 status-onboarded：六個 transaction/code、三個
  invitation、八個 identity/profile、七個 membership/grant、七個
  client/token functions，以及 `_iso_row`、`_user_from_row` 兩個
  row-mapping helpers。
- 35 個本批 N/A-reason hygiene mappings 已逐條清理；production code
  未修改。
- Reviewer blocker hardening 固定四個 identity reads 的 exact keyed SQL、
  parameter dictionaries、not-found result 與 zero transaction/write/audit
  side effects；另固定 `get_token_session`、`list_token_sessions` 即使 row
  已 expired 或 revoked，仍保留 `expires_at`、`revoked_at`、
  `revocation_reason`，且 repository read 不做 expiry/revocation filtering。
- Final repository `:ro` proof：兩個 exact regressions、owner module
  22/22、scoped onboarding 2/2、target harness 12/12、direct trace 33/33、
  46 checked evidence pairs、0 target blockers、0 source-binding mismatches，
  加上 targeted Ruff、manifest JSON 與 diff checks。
- Engineering、governance/safety、manifest/onboarding reviewers 最終 3/3
  `RELEASE_DECISION: AGREE`；原 blockers 均由原 reviewers re-review 關閉。
  這是 bounded batch completion，不是 live PostgreSQL、external evidence、
  Issue #20 completion、production readiness 或 Issue #20-wide reviewer
  external layer。

### 16. Runner boundary 10-new／1-refreshed batch

- 10 個 `scripts.issue20_runner_boundary` functions 已 status-onboarded；
  `verify_inner_boundary` 因完整 capability-set validation 而 refresh。
- Production safety fixes 讓 `lock-and-exec` 透過已開啟 descriptor 固定
  validated canonical runner inode，即使 path 在驗證後被替換也不會執行
  replacement；post-`dup2` `execve()` failure 會 restore 原 fd 9 並關閉
  lock、backup、script 等 temporary descriptors。
- `verify_inner_boundary` 現在要求 `CapInh`、`CapPrm`、`CapEff`、
  `CapBnd`、`CapAmb` 五個欄位全部存在、為有效十六進位且數值為 0。
- Final repository `:ro` proof：exact regression 1/1、runner module
  33/33（`ResourceWarning` 視為 error）、scoped onboarding 1/1、target
  harness 16/16、23 checked evidence pairs、direct trace 11/11、0 target
  blockers、0 source-binding mismatches，加上 targeted Ruff、manifest JSON
  與 diff checks。
- Engineering、governance/safety、manifest/onboarding reviewers 最終 3/3
  `RELEASE_DECISION: AGREE`。最後 blocker 要求 `os.open` flags 必須精確
  等於 `O_RDONLY | O_NOFOLLOW | O_CLOEXEC`，不得額外加入
  `O_NONBLOCK`；修正後由原 reviewer re-review 關閉。
- Fresh whole-manifest execution 通過 285/285 tests，direct trace
  362/362，831 checked evidence pairs，execution blockers 為 0。這仍是
  bounded repository evidence，不是 external evidence、Issue #20
  completion 或 production readiness。

### 16.1 Runner private failure-diagnostic custody

- Production change is in
  `scripts/connected_operator_postgres_live_journey.py`. Regression and
  authority evidence is in
  `tests/test_connected_operator_postgres_live_journey.py`,
  `tests/test_issue20_containerized_evidence_runner.py`,
  `tests/test_issue20_function_onboarding.py`, and
  `tests/issue20_function_harness_manifest.json`. Current durable status is
  synchronized in this document, `docs/implementation-task-breakdown.md`, and
  `docs/agent-goals/handoff-log.md`.
- Canonical operator invocation 把固定、private、campaign-scoped final
  diagnostic path 交給 outer process；它位於 governed `private-logs`，不在
  reports、trust inputs、external layers、completion sources 或 packet
  inputs。Inner runtime UID `10001` 不會寫入這個 final path。
- Inner failure 只可在既有 private temporary directory 建立 ephemeral
  handoff：寫入時 exclusive mode `0200`，`fsync` 後改為 mode `0444`。
  Outer 以 no-follow descriptor 驗證 `10001:10001` owner、regular /
  single-link、固定 inode 與 metadata、bounded canonical JSON、exact
  five-field schema，且只接受 closed enum 內的 `inside_*` stage。成功 child
  run 若留下 handoff 必須 fail closed；missing／malformed／raced handoff
  只會降級成 `outer_inner_journey`。
- 驗證完成後，outer 才建立 runner-owned mode `0400` final diagnostic。
  Ephemeral handoff 不是 report、trust input、external layer、completion
  source、packet input 或 campaign lock artifact。
- Runner 只接受 exact five-field schema：
  `artifact_id`、`failure_code`、`schema_version`、`stage`、`status`。
  Constants 固定為 v1 diagnostic artifact、`stage_failed`、version `1`
  與 `failed`；stage 是 runbook 列出的 12-value closed enum。
- Final diagnostic validation 使用 no-follow descriptor、regular/single-link、
  runner owner、mode `0400`、fixed-path inode、bounded UTF-8 JSON、
  duplicate-key rejection 與 exact schema/value checks。Missing、malformed、
  unknown、extra-key、symlink、replacement、wrong owner/mode 或 oversized
  diagnostic 都不可信。
- Public output 不讀 child stderr 或 private run log。失敗仍使用
  runner-owned generic `runner_command_failed`；只有完全驗證過的 finite
  stage 可以附加。Diagnostic write/read/validation failure 不得取代原始
  command failure，也不得產生 private detail。
- At the 2026-07-20 cross-UID checkpoint, canonical read-only proof passed exact
  handoff regressions 6/6, operator module 28/28, containerized runner 38/38,
  target harness 25/25 across 51 evidence pairs, target trace 33/33, and global
  605/605/605 authority with
  whole-manifest 460/460/460/460 across 1,223 pairs, trace 605/605, and
  `test_id_count` 1,434. Skips, failures, errors, resolution/execution blockers,
  and validator blockers are zero. Full
  Ruff check/format, manifest JSON, runner shell syntax, container diff-check,
  and untracked text-style checks pass. The original governance reviewer
  completed the finding-specific re-review with 1/1
  `RELEASE_DECISION: AGREE`, so the custody finding is closed. This preserves
  the existing connected-operator batch reviewer gate at 3/3; the author and
  the read-only verification-only agent are not counted as reviewers.
- 固定 diagnostic 一旦存在，preflight、operator、operator-layer、
  live-PostgreSQL、兩次 lifecycle、lifecycle aggregation 與 local
  harness 全部會在 Docker build/run 前 fail closed。成功 operator run
  也必須證明 diagnostic path 不存在。Failed campaign 必須保留鎖定，
  只能治理式 reset 整個 scratch root 後重新開始。
- Canonical pre-fix evidence 為新兩個 regression 0/2；修正後
  read-only、`--network none` focused checks 3/3 與完整 runner module
  36/36 通過。這一輪沒有執行 live campaign；本項只是 runner-side
  diagnostic custody，不提供任何 external-layer 或 production-readiness
  證據。

### 17. Evidence-packet 56-function batch

- 全部 56 個 `formowl_evidence.issue20_packet` functions 已
  status-onboarded。Scoped validator 對本批為 0 target blockers、0
  source-binding mismatches。
- Final repository `:ro` proof 通過 packet module 37/37、exact onboarding
  1/1、target harness 14/14，以及 direct trace 56/56／69 checked evidence
  pairs。Final reviewer delta 只強化測試，證明 unrelated manifest status
  transition 不會改變 packet batch partition；沒有修改 production code、
  manifest data 或 source bindings。
- Engineering、governance/safety、manifest/onboarding reviewers 最終 3/3
  `RELEASE_DECISION: AGREE`。
- At this batch checkpoint，validator 推進至 418/601 onboarded、183 pending、411
  blockers（183 pending-function 加 228 N/A-reason hygiene），binding
  mismatches 為 0。這是 bounded repository-side packet validation，
  不是 accepted external evidence、Issue #20 completion 或 production
  readiness。

### 18. Connected-runtime live-E2E 56-function batch

- 既定 56 個 `scripts.connected_runtime_postgres_live_e2e` targets 已
  status-onboarded；production code 在 final reviewer delta 中未修改。
- 五個直接 negative regressions 分別覆蓋 `_load_inside_dependencies`
  protocol-version mismatch、bearer denial、malformed `_tool_call_result`、
  malformed／error `_structured_call`，以及 delegated
  `_tool_call_is_error` validation。
- Final repository `:ro` proof：owner module 84/84、exact
  onboarding／isolation 2/2、target harness 59/59、direct trace 56/56、
  106 checked evidence pairs、scoped validator 0 target blockers，並通過
  targeted Ruff check／format-check、manifest JSON 與 `git diff --check`。
- Engineering、governance/safety、manifest/onboarding reviewers 最終 3/3
  `RELEASE_DECISION: AGREE`。這是 bounded repository-side journey
  evidence，不是 accepted external evidence、Issue #20 completion 或
  production readiness。
- 後續 `_invalid_token_challenge`、`_validate_external_layer_counts`、
  31-function `oauth_mcp_harness` 與 29-function connected operator journey
  都已分別完成 status onboarding 與各自 3/3 reviewer gate；這些仍是
  bounded repository evidence，不能互相替代或自動滿足 external layer。

### 19. Final lifecycle-probe 與 runtime readiness closeout

- 在該 602-function lifecycle closeout checkpoint，最後 66 個
  `scripts.connected_runtime_container_lifecycle_probe` functions 已全部
  status-onboarded，完成 602/602/602
  changed／manifested／onboarded authority；所有 pending、hygiene、
  inventory、binding 與 validator blocker counts 都是 0。
- `_runtime_data_stores_ready` 對 transient unlink cleanup fault 會重試一次；
  descriptor-close fault 或任何 cleanup fault 都使 readiness fail closed，
  同時仍嘗試移除 probe。Public readiness result 保持 generic，不輸出
  data directory、probe path 或 private exception detail。
- 該 checkpoint 的 repository evidence 為 focused runtime／onboarding
  38/38、scoped harness 24/24、direct trace 15/15、missing 0、57 checked
  evidence pairs，exact manifest validator 602/602 onboarded 且
  0 blockers／mismatches。
- Engineering、governance/safety 與 manifest/onboarding scoped reviewers
  最終 3/3 `RELEASE_DECISION: AGREE`、zero blockers。這不等於尚未提供的
  Issue #20-wide `reviewer_gate` external layer。

## Authoritative harness 現況

下表是 2026-07-21 的 local repository authority。它證明 current source
與 manifest 的本機 harness 已一致，不代表真實 PostgreSQL、production
container、MCP Inspector、ChatGPT／Google 或 Issue-wide review 已完成。

| 指標 | 數量 |
| --- | ---: |
| manifest function entries | 689 |
| current changed-function inventory | 689 |
| 已完成 harness onboard | 689 |
| manifest pending entries | 0 |
| global validator blockers | 0 |
| pending-function / N/A-reason hygiene blockers | 0 / 0 |
| missing / extra / duplicate functions | 0 / 0 / 0 |
| source-binding mismatches | 0 |
| whole-manifest requested / resolved / run / pass | 508 / 508 / 508 / 508 |
| whole-manifest skips / failures / errors | 0 / 0 / 0 |
| resolution / execution blockers | 0 / 0 |
| whole-manifest checked evidence pairs | 1,388 |
| whole-manifest direct trace covered / missing | 689 / 0 |
| whole-manifest direct trace blockers | `[]` |
| whole-manifest `test_id_count` | 1,521 |
| root local harness validation | passed |
| focused runtime | 36 / 36 |
| focused safe-start | 71 / 71 |
| canonical full suite / environment-gated skips | 1,521 / 7 |
| canonical full-suite timing | 964.613s |
| Ruff check / Ruff format | passed / 306 files already formatted |
| runner shell / JSON parse / git diff | passed / passed / passed |
| latest harness artifact SHA-256 | `1adaeaf752148e730f421e0e385b0faa4a1aef4273d437def902bdb212e352b1` |
| fresh Issue-wide reviewer packet | required after source freeze |
| external evidence blockers | 7 / 7 `not_supplied` |

| Claim | 值 |
| --- | --- |
| `scoped_function_test_execution_verified` | `true` |
| `fresh_post_batch_whole_manifest_execution_verified` | `true` |
| `function_manifest_verified` | `true` |
| `function_onboarding_verified` | `true` |
| `supports_issue20_closure_claim` | `false` |
| `supports_production_ready_claim` | `false` |

這表示 local repository function authority 已完成，不再有本機
onboarding blocker。它仍不支援 closure：所有七個 external layers
保持 `not_supplied`，且 final scoped 3/3 reviewer agreement 不能代替
Issue-wide `reviewer_gate`。

## Canonical repository verification 與 historical full-suite note

Current Issue #20 repository authority 是 whole-manifest
508/508/508/508 requested／resolved／run／pass、1,388 checked evidence
pairs、`test_id_count` 1,521，且 skips、failures、errors、resolution
blockers、execution blockers 與 validator blockers 皆為 0。Exact manifest
validator 同時確認 689/689 functions onboarded，direct trace
689/689、missing 0，沒有 inventory、binding、pending 或 hygiene blocker。

Canonical full suite 精確輸出為 `Ran 1521 tests in 964.613s`、
`OK (skipped=7)`。Ruff check、306-file Ruff format check、runner shell
syntax、JSON parse 與 `git diff --check` 全部通過。以下舊數字僅保留為
immutable historical
checkpoint：605/605/605、
460/460/460/460、1,223 pairs、`test_id_count` 1,434 與
`Ran 1219 tests / failures=1 / skipped=6` 都是 2026-07-20 或更早的歷史
checkpoints，不再代表目前 Issue #20 authority。

Local-folder observation-order finding 已不在 failure 清單。Production
extractor 與 completed job 原本就保留 source order；generic
file/PostgreSQL store `.list()` 則沒有 source-order contract。測試現在
重新載入 completed `IngestionJob`，沿其 `observation_ids` 逐筆 `get()`，
明確拒絕 missing persisted observation，並驗證 heading／paragraph order
與完整 `source_ref`。Exact 1/1、local-folder module 10/10、相關
text-extraction／ingestion-workflow 14/14、targeted Ruff check／format-check
與 `git diff --check` 均通過；generic store ordering 與 stable IDs 未修改。
其 engineering、governance/safety、test-methodology reviewer gate 為 3/3
`RELEASE_DECISION: AGREE`。

## Reviewer finding 狀態與外部證據

二十個 reviewer-gated finding 都已關閉各自的 scoped implementation／review
gate，但都不能替代 Issue #20-wide final reviewer evidence：

1. configured sync handler／nested container coroutine finding 的 hardening
   candidate 已實作，包含 stateful `Mapping`、cycle、native coroutine
   cleanup 與 custom-awaitable fail-closed coverage；canonical `:ro`
   focused verification 已通過。Coroutine-scoped fresh final 3-reviewer
   gate 已由 engineering、manifest/onboarding、governance/safety reviewer
   3/3 AGREE，沒有 blocker；所以分類為
   **candidate-fixed／scoped gate complete**，而非 unresolved engineering
   defect。
2. real semantic handler 的 NaN／`+Inf`／`-Inf` audit-truthfulness finding
   已由 production `_safe_handler_envelope` 修正。真實 bearer-authenticated
   exact `/mcp` HTTP regressions、scoped 15/15、trace 1/1、Ruff／JSON／diff
   checks 與 fresh 3-reviewer gate 均通過，分類為
   **fixed／scoped gate complete**。
3. read-only wheel/package finding 只修改 test harness：source staging 在
   writable `/tmp`，repository 維持 `:ro`，production packaging 未改。
   Exact 1/1、module 15/15、Ruff check／format-check 與 engineering、
   governance/safety、packaging/test-methodology reviewer 3/3 AGREE。
4. local-folder observation-order finding 只修正測試的順序權威來源：
   persisted `IngestionJob.observation_ids`，沒有改動 generic store ordering
   或 stable observation IDs。Exact 1/1、module 10/10、related 14/14、
   Ruff check／format-check、`git diff --check` 與 engineering、
   governance/safety、test-methodology reviewer 3/3 AGREE。
5. implementation-contract-hash function onboarding 沒有修改 production：
   focused 3/3、module 14/14、scoped trace 1/1、Ruff／JSON／diff checks
   通過，engineering、governance/safety、test-methodology reviewer 3/3
   `RELEASE_DECISION: AGREE`，zero blockers。
6. manual trusted `select_actor` 的真實 audit-failure ordering defect 已修正：
   audit durable 後才提交 actor context。Focused 4/4、provider module 2/2、
   function-scoped execution 3/3、direct trace 1/1、Ruff／JSON／diff checks
   通過；workspace ID/role 與 audit session/target lineage assertions 關閉
   兩個 reviewer blockers後，engineering、governance/safety、
   test-methodology reviewer 3/3 `RELEASE_DECISION: AGREE`。
7. `ExternalIdentity.to_dict` 的 exact serializer contract 已完成：
   fixed ten-field payload、九個 exact `str` fields、exact `bool`
   `email_verified`、canonical verified-email equality，以及 no
   copy-hook／input-leak／state-mutation proof。Pre-fix email regression
   真實失敗兩次；final exact 1/1、module 19/19、onboarding 1/1、validator
   0 mismatches／0 blockers、harness 1/1、trace 1/1、Ruff／JSON／diff
   checks 均通過。Engineering、governance、manifest reviewer 3/3
   `RELEASE_DECISION: AGREE`；兩個 blockers 由原 reviewer re-review 關閉。
8. 17-target OAuth models batch 已 status-onboarded；惡意 non-string key
   即使與允許的 string key 發生 equality/hash collision，也會在
   dictionary materialization 前 fail closed，同時保留 generic
   `Mapping` compatibility。Engineering、governance/safety、
   manifest/onboarding reviewer 為 3/3 `RELEASE_DECISION: AGREE`。這是
   bounded batch completion，不是 Issue #20 completion 或 production
   readiness。
9. 22-target exact `/mcp` 到 `open_upload_session` batch 已
   status-onboarded，包含 remote 13、runtime 七、mail upload 兩個
   functions，沒有 production change。Scoped validator 為 0 target
   blockers／0 source-binding mismatches；exact 4/4、related
   gateway/runtime/mail 92/92、onboarding module 排除 intentional global
   gate 後 26/26、target harness 21/21、direct trace 22/22／52 evidence
   pairs 均通過。Engineering、governance/safety、manifest/onboarding
   reviewers 3/3 `RELEASE_DECISION: AGREE`。原 reviewers re-review 後
   關閉三個 blockers：outer middleware temporal N/A ordering、
   `audit_lineage` middleware ownership wording，以及 scoped test 的固定
   global-total coupling。這是 bounded batch gate，不是 Issue #20-wide
   reviewer external evidence。
10. 22-target `formowl_gateway.operator` batch 已 status-onboarded，沒有
    production change。Public `lookup_token_session` 的 timestamp path
    現在證明 non-UTC clock 會 normalization 到 UTC；惡意
    `utcoffset()`／`astimezone()` exception 只回 generic error，且在
    repository call、transaction、audit 與 mutation 前 fail closed。
    Exact onboarding 1/1、timestamp regressions 3/3、operator module 13/13、
    target harness 12/12、direct trace 22/22／69 evidence pairs、
    runtime/CLI/restart/entrypoint 5/5，以及排除 intentional global gate
    的 onboarding 27/27 均通過。Engineering、governance/safety、
    manifest/onboarding reviewers 3/3 `RELEASE_DECISION: AGREE`。這是
    bounded batch completion，不是 Issue #20 completion、production
    readiness 或 Issue #20-wide reviewer external evidence。
11. Connected startup／secret 25-function batch 已 status-onboarded，包含
    `secret_init` 13 與 `container_entrypoint` 12 functions。Production
    close／final-ownership／quarantine rollback fixes 與 signing
    `verify_until`、staged-secret write/fchown/fsync/close regressions 均有
    executable evidence。Exact 1/1、entrypoint 12/12、onboarding 1/1、
    validator 0 blockers／mismatches、harness 21/21、trace 25/25／53 pairs
    通過；三個 reviewer streams 關閉五項具體 blockers後，最終 3/3
    `RELEASE_DECISION: AGREE`。這是 bounded batch completion，不是 Issue
    #20 completion、production readiness 或 Issue #20-wide reviewer
    external evidence。
12. PostgreSQL migration／transaction 25-function batch 已
    status-onboarded，並修復 34 個既有 N/A-reason hygiene mappings。
    Owner modules 32/32、scoped onboarding 1/1、target harness 9/9、direct
    trace 25/25／31 evidence pairs 與 scoped validator 0 blockers／
    mismatches 均通過。唯一 test hardening 是 repository-wrapper
    `apply_migrations` rollback／no-partial-state regression，以及
    `PostgreSQLMigrationResult.to_safe_dict` safe result boundary；
    production code 未修改。Engineering、governance/safety、
    manifest/onboarding reviewers 3/3 `RELEASE_DECISION: AGREE`。這不是
    live PostgreSQL、Issue #20 completion、production readiness 或 Issue
    #20-wide reviewer external evidence。
13. PostgreSQL CRUD／row-mapping 33-function batch 已 status-onboarded：
    transaction/code 六個、invitation 三個、identity/profile 八個、
    membership/grant 七個、client/token 七個、row mapping 兩個；35 個
    本批 N/A-reason hygiene mappings 已逐條清理，production code 未改。
    四個 identity reads 的 keyed SQL、not-found、zero-side-effect
    regressions 與兩個 token reads 的 expired/revoked lifecycle-field
    preservation regression 通過；owner 22/22、scoped 2/2、harness 12/12、
    trace 33/33／46 pairs、target blockers／binding mismatches 0。三個
    reviewer streams 最終 3/3 `RELEASE_DECISION: AGREE`，原 blockers 均由
    原 reviewers 關閉。這不是 live PostgreSQL、Issue #20 completion、
    production readiness 或 Issue #20-wide reviewer external evidence。
14. Runner boundary batch 已 status-onboarded 10 個新 functions，並 refresh
    `verify_inner_boundary`。Production fixes 固定 canonical runner inode
    across path swap、在 post-`dup2` execution failure restore／cleanup
    fd 9，且驗證五個 capability sets 都存在且為 0。Exact 1/1、module
    33/33、onboarding 1/1、harness 16/16／23 pairs、trace 11/11、target
    blockers／mismatches 0，fresh whole-manifest 285/285、trace 362/362／
    831 pairs、execution blockers 0。最後 exact open-flags blocker 修正後，
    三個 reviewer streams 最終 3/3 `RELEASE_DECISION: AGREE`。這不是
    external evidence、Issue #20 completion 或 production readiness。
15. Evidence-packet batch 已 status-onboarded 全部 56 個
    `formowl_evidence.issue20_packet` functions。Packet module 37/37、
    exact onboarding 1/1、target harness 14/14、direct trace 56/56／69
    pairs、target blockers／binding mismatches 0。Final reviewer delta
    只增加 unrelated-status partition regression，沒有修改 production
    code、manifest data 或 source bindings；三個 reviewer streams 最終
    3/3 `RELEASE_DECISION: AGREE`。這是 bounded repository-side packet
    validation，不是 accepted external evidence、Issue #20 completion 或
    production readiness。
16. Connected-runtime live-E2E batch 已 status-onboarded 既定 56 個
    `scripts.connected_runtime_postgres_live_e2e` functions。Owner 84/84、
    exact onboarding／isolation 2/2、harness 59/59、trace 56/56／106
    pairs、五個直接 negative regressions 與 scoped validator 0 target
    blockers 均通過；engineering、governance/safety、manifest/onboarding
    reviewers 3/3 `RELEASE_DECISION: AGREE`。當時 current source 新增的
    `_invalid_token_challenge` 仍需獨立 onboarding，不能由此 batch 自動
    涵蓋。這不是 accepted external evidence、Issue #20 completion 或
    production readiness。
17. `_invalid_token_challenge` 已作為獨立 changed function
    status-onboarded。Current owner module 85/85、onboarding/isolation 2/2、
    target harness 60/60、direct trace 57/57／108 pairs 與 target
    blockers 0 均通過；engineering、governance/safety、
    manifest/onboarding reviewers 3/3 `RELEASE_DECISION: AGREE`。這不會
    反向擴張第 16 項 56-function batch 的歷史 claim boundary。
18. `scripts.oauth_mcp_harness._validate_external_layer_counts` 已
    status-onboarded test-only。Focused 3/3、one-function harness 2/2、
    direct trace 1/1 且 missing 0、related module 41/41、target blockers
    0 均通過；補上 live PostgreSQL 與 production lifecycle exact
    count branches 的 deletion-proof 後，三個 reviewer streams 最終
    3/3 `RELEASE_DECISION: AGREE`。Production、manifest data 與 source
    binding 未在 final blocker fix 中改動。
19. 其餘 31 個 `scripts.oauth_mcp_harness` functions 已
    status-onboarded。Production `main` 的四個 CLI output branches 全部
    改用 atomic JSON write；injected output `OSError` 會保留既有
    authoritative bytes、清除 temporary file、保持 stdout 空白、只在
    stderr 輸出固定 generic `output_write_failed` JSON，並回傳 1。
    `LifecycleEvidenceError` 與 `OperatorEvidenceError` 的 hostile-code
    fallback 由 test-only regression 補足，production constructors 不需
    修改。Final `:ro` proof 為 target harness 15/15、trace 31/31／52
    pairs、related module 44/44 in 466.509s、scoped onboarding 1/1、
    Ruff check／format、manifest JSON、diff／whitespace checks，以及三個
    reviewer streams 3/3 `RELEASE_DECISION: AGREE`。
20. Final lifecycle-probe／runtime readiness closeout 已完成；在該歷史
    checkpoint 為 602/602/602 changed／manifested／onboarded、
    whole-manifest 445/445/445/445、1,202 pairs，所有 pending、inventory、
    binding、validation、resolution 與 execution blocker counts 都是 0。
    Descriptor-close 或 cleanup fault 會 fail readiness closed，且 cleanup
    仍會被嘗試；focused runtime／onboarding 38/38、scoped harness 24/24、
    trace 15/15／57 pairs 通過。Engineering、governance/safety、
    manifest/onboarding scoped reviewers 3/3
    `RELEASE_DECISION: AGREE`、zero blockers。

Authoritative harness 中七個 required external gates 仍全部為
`not_supplied`；上述二十個 scoped 3-reviewer gates 都不等同完成
Issue #20-wide `reviewer_gate`：

1. `live_postgresql`
2. `operator_cli_postgresql`
3. `production_container_lifecycle`
4. `mcp_inspector`
5. `live_chatgpt_google`
6. `reviewer_gate`
7. `completion_audit`

本機 authoritative harness 已通過；剩餘 blocker 全部是上述外部證據，
不是 repository onboarding 或 local execution failure。

## Issue #41 與 release decision

Issue #20 解決「人是誰、目前 workspace、role／grant」。它不單獨解決
檔案 tenant、owner、byte dedup、occurrence、retention、purge 與跨使用者
隔離。真實 PST、mail 或其他檔案進入多人封測前，Issue #41 是 blocking
dependency；不得把所有人的檔案放進無 scope 的共用 ownership namespace。

PM 建議：

- 內部開發與 controlled test：可繼續。
- 小規模真實資料封測：production-shaped `open_upload_session` E2E 已使用
  正確 session identity 通過；仍須完成 Issue #41 最低 tenant／owner
  isolation 與對應真實外部 journey。
- production 或宣稱 Issue #20 完成：不可。

建議順序：

1. Preserve stale scratch 作為 non-authoritative history，freeze final
   post-cleanup source、docs 與 local harness authority。
2. 僅在 freeze 後依固定順序執行全部八個 local campaign stages，再執行
   `live_postgresql`、`operator_cli_postgresql`、
   `production_container_lifecycle`、`mcp_inspector` 與
   `live_chatgpt_google` external evidence campaigns。
3. 以上述 frozen-source evidence 準備 fresh Issue-wide `reviewer_gate`
   source；先前三個 source reviews 不可替代此 layer。
4. Reviewer layer 通過後，再執行獨立 `completion_audit`；七層全部
   supplied 且一致前，Issue #20 保持 open。

## PM 可直接引用

> FormOwl Issue #20 已完成多數帳號、OAuth、Google 身分映射、token、
> current-state authorization、revocation、rollback、audit 與 leak safety
> 的 repository-side 驗證。Current changed／manifested／onboarded
> authority 是 689/689/689；pending、missing、extra、duplicate、
> source-binding mismatch 與 validator blockers 全部為 0。
> Final local whole-manifest requested／resolved／run／pass 為
> 508/508/508/508，共檢查 1,388 evidence pairs，`test_id_count` 1,521；
> direct trace 689/689、missing 0，skips／failures／errors 與
> resolution／execution／validator blockers 全部為 0。
> Production-shaped upload-session E2E
> 已使用有效 `SessionIdentity` 通過，exact/runtime/gateway/onboarding
> checks 分別為 1/1、34/34、45/45、1/1，slice reviewer gate 3/3 AGREE，
> 且未弱化 production fail-closed validation。NaN／`+Inf`／`-Inf`
> audit-truthfulness finding 亦已由 `_safe_handler_envelope` 修正，真實
> bearer exact `/mcp` E2E、scoped 15/15、trace 1/1、Ruff／JSON／diff 與
> scoped reviewer 3/3 AGREE 均通過；這不是 Issue #20-wide final reviewer
> evidence。Read-only wheel-build harness 亦已完成 focused 1/1、相關
> module 15/15、targeted Ruff verification 與 scoped reviewer 3/3 AGREE；
> fresh canonical full-suite 中 wheel failure 已消失。Validator synthetic
> self-test 也已改為 bounded synthetic context，focused 1/1 通過且相關
> 22-test module 的 scoped checks 通過，scoped reviewer gate 3/3 AGREE
> 且無 blocker；後續 final closeout 已關閉 global onboarding gate。
> Local-folder test 現改沿 persisted job `observation_ids` 驗證 source
> order，focused 1/1、module 10/10、related 14/14、Ruff check／format、
> `git diff --check` 與 scoped reviewer 3/3 AGREE 均通過，沒有修改
> generic store order 或 stable IDs。Implementation-contract-hash function
> 亦完成 focused 3/3、module 14/14、scoped trace 1/1、Ruff／JSON／diff
> checks，production 未修改，scoped reviewer gate 3/3 AGREE 且 zero
> blockers。Manual trusted `select_actor` 亦修正真實 audit-failure
> ordering defect：audit durable 後才提交 actor context；focused 4/4、
> provider module 2/2、function-scoped execution 3/3、direct trace 1/1
> 與 scoped reviewer gate 3/3 AGREE 均通過，兩個 assertion blockers
> 已關閉。`ExternalIdentity.to_dict` 亦完成 exact ten-field serializer
> contract：九個 string fields 與 `email_verified` 分別要求 exact
> `str`／`bool`，verified email 必須已是 canonical normalized form，
> malformed 或 noncanonical email 以固定 generic error fail closed，
> 且不呼叫 copy hooks、不洩漏 input、不修改 object state。Pre-fix email
> regression 真實失敗兩次；final exact 1/1、module 19/19、onboarding
> 1/1、validator 0 mismatches／0 blockers、harness 1/1、trace 1/1、Ruff／
> JSON／diff 與 reviewer 3/3 AGREE 均通過，兩個 blockers 已由原 reviewer
> re-review 關閉。17-target OAuth models batch 亦已 status-onboarded；
> malicious non-string colliding key 會 fail closed，generic `Mapping`
> compatibility 維持，engineering／governance／manifest reviewer 3/3
> AGREE。22-target exact `/mcp` 到 `open_upload_session` batch 亦完成
> remote 13、runtime 七、mail upload 兩個 functions 的 status
> onboarding，沒有 production change；scoped validator 0
> blockers／mismatches、exact 4/4、related 92/92、onboarding 26/26、
> target harness 21/21、trace 22/22／52 pairs 與 engineering／
> governance／manifest reviewer 3/3 AGREE 均通過。Temporal N/A
> middleware ordering、audit-lineage middleware ownership wording與
> fixed-global-total coupling 三個 blockers 都由原 reviewer re-review
> 關閉。22-target `formowl_gateway.operator` batch 也已完成 status
> onboarding，沒有 production change；public token lookup 已驗證
> non-UTC normalization，以及惡意 `utcoffset()`／`astimezone()`
> exception 的 generic error、zero repository/transaction/audit/mutation
> side-effect boundary。Exact 1/1、regressions 3/3、module 13/13、harness
> 12/12、trace 22/22／69 pairs、runtime/CLI/restart/entrypoint 5/5、
> onboarding 27/27 與 engineering／governance／manifest reviewers 3/3
> AGREE 均通過。這些仍只是 bounded batch gates，不是尚為
> `not_supplied` 的 Issue #20-wide reviewer external layer。Connected
> startup／secret 25-function batch 亦完成 `secret_init` 13 與
> `container_entrypoint` 12 functions 的 onboarding；production
> close／final-ownership／quarantine rollback fixes、signing
> `verify_until` assertion、staged-secret write/fchown/fsync/close cleanup
> regression、exact 1/1、entrypoint 12/12、harness 21/21、trace
> 25/25／53 pairs 與 reviewers 3/3 AGREE 均通過。這仍不替代
> Issue #20-wide reviewer external layer。PostgreSQL
> migration／transaction 25-function batch 亦完成 onboarding 與 34 個
> N/A-reason hygiene mappings；owner modules 32/32、scoped onboarding
> 1/1、target harness 9/9、trace 25/25／31 pairs 與 reviewers 3/3 AGREE
> 均通過。Production code 未修改，唯一 test hardening 是
> `apply_migrations` rollback／no-partial-state regression 與
> `PostgreSQLMigrationResult.to_safe_dict` safe result boundary。PostgreSQL
> CRUD／row-mapping 33-function batch 亦完成六 transaction/code、三
> invitation、八 identity/profile、七 membership/grant、七
> client/token 與兩 row-mapping functions 的 onboarding，並逐條清理
> 35 個本批 N/A hygiene mappings；production 未改。四個 identity reads
> 的 keyed/not-found/zero-side-effect regressions，以及兩個 token reads
> 的 expired/revoked field-preservation regression 通過；owner 22/22、
> scoped 2/2、harness 12/12、trace 33/33／46 pairs、target blockers／
> mismatches 0，reviewers 3/3 AGREE，原 blockers 均由原 reviewers
> 關閉。Runner boundary batch 亦完成 10 個新 functions 與
> `verify_inner_boundary` refresh；canonical runner inode pin、fd 9
> restore／cleanup、五組 capability sets zero，以及 exact 1/1、module
> 33/33、onboarding 1/1、harness 16/16／23 pairs、trace 11/11、target
> blockers／mismatches 0 均有 executable evidence。Exact open-flags
> blocker 修正後 reviewers 3/3 AGREE。Evidence-packet batch 亦完成全部
> 56 個 `formowl_evidence.issue20_packet` functions；packet module
> 37/37、exact onboarding 1/1、harness 14/14、trace 56/56／69 pairs、
> target blockers／binding mismatches 0，reviewers 3/3 AGREE。Final
> reviewer delta 只增加 unrelated-status partition regression，沒有修改
> production code、manifest data 或 source bindings。這是 bounded
> repository-side packet validation，不是 accepted external evidence。
> Connected-runtime live-E2E batch 也完成既定 56 個
> `scripts.connected_runtime_postgres_live_e2e` functions 的 status
> onboarding；owner 84/84、exact onboarding／isolation 2/2、harness
> 59/59、trace 56/56／106 pairs、五個直接 negative regressions 與
> reviewers 3/3 AGREE 均通過。其後 `_invalid_token_challenge` 已獨立
> status-onboarded；current owner module 85/85、onboarding/isolation
> 2/2、harness 60/60、trace 57/57／108 pairs 與 reviewers 3/3 AGREE
> 均通過。`_validate_external_layer_counts` 也已 test-only
> status-onboarded；focused 3/3、one-function harness 2/2、trace 1/1
> missing 0、related 41/41、target blockers 0 與 reviewers 3/3 AGREE
> 均通過。其餘 31 個 `scripts.oauth_mcp_harness` functions 也已
> status-onboarded；atomic output failure 保留舊 artifact 並只輸出
> generic error，hostile constructor fallback 有 test-only proof；
> harness 15/15、trace 31/31／52 pairs、related 44/44、onboarding 1/1、
> Ruff／JSON／diff 與 reviewers 3/3 AGREE 均通過。這些仍只是 bounded
> repository evidence，不是 accepted external evidence。
> Final runtime cleanup 已移除 return-in-`finally`；既有
> `test_upload_store_readiness_probe_is_atomic_clean_and_fail_closed` 證明
> descriptor-close fault 後 cleanup 仍執行且 readiness fail closed，
> focused runtime 36/36。Implementation contract 綁定 tracked deploy
> templates/examples 而非 ignored operator-local Caddy/env copies；real
> BuildKit current-source/frozen-snapshot equality 與 safe-start 71/71
> 通過。Finalization computation fault 轉為 generic failed validation，
> strengthened regression 與 onboarding manifest update 亦通過。Canonical
> full suite 是 `Ran 1521 tests in 964.613s`、`OK (skipped=7)`；Ruff check、
> 306-file format check、runner shell syntax、JSON parse 與 diff check 通過。
> Latest harness artifact 為
> `/tmp/formowl-issue20-postfix-local-harness-20260721T100124Z.json`，SHA-256
> `1adaeaf752148e730f421e0e385b0faa4a1aef4273d437def902bdb212e352b1`。
> 先前三個 source reviewers 早於 final cleanup，不能替代 fresh
> frozen-source Issue-wide reviewer packet。
> 七個 external layers `live_postgresql`、`operator_cli_postgresql`、
> `production_container_lifecycle`、`mcp_inspector`、
> `live_chatgpt_google`、Issue-wide `reviewer_gate` 與
> `completion_audit` 仍全部 `not_supplied`。因此 Issue #20 保持 open，
> 不支援 closure 或 production-readiness claim。
