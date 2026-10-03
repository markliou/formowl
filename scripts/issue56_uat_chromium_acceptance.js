'use strict';

// Real Chromium + actual HTML form. --self-check tests tooling only, not UAT.
// No external request is made unless the operator explicitly supplies --live.
const {spawn} = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

// Allow bounded cold-start variance while remaining below the configured
// 180-second UAT turn ceiling used for live acceptance.
const CDP_COMMAND_TIMEOUT_MS = 90000;
const MAX_PROVIDER_ATTEMPT_DIAGNOSTICS = 3;
// Three MCP calls + one terminology call, followed by the final answer and
// its single bounded repair.
const MAX_PROVIDER_REQUESTS_PER_TURN = 3 + 1 + 2;
const MAX_UAT_TURN_MS = 120000;
const safeRunnerPhases = new Set([
  'startup', 'browser_launch', 'cdp_connect', 'target_create',
  'page_navigation', 'auth_gate', 'ready_check', 'ordinary_submit',
  'ordinary_wait', 'mail_submit', 'mail_wait', 'document_submit',
  'document_wait', 'cleanup', 'self_check',
  'unknown',
]);
const safeRunnerFailureReasons = new Set([
  'auth_required', 'browser_missing', 'cdp_closed', 'cdp_error',
  'cdp_parse_error', 'cdp_timeout', 'child_error', 'child_exit',
  'child_signal', 'page_evaluation_failed', 'page_not_ready',
  'pipe_closed', 'pipe_error', 'pipe_reset', 'request_control_failed',
  'screenshot_capture_failed', 'session_not_fresh', 'spawn_error',
  'target_invalid', 'timeout_invalid', 'turn_timeout', 'unknown_failure',
]);
const safeCdpCommands = new Set([
  'Browser.getVersion',
  'Target.createBrowserContext',
  'Target.createTarget',
  'Target.attachToTarget',
  'Page.enable',
  'Runtime.enable',
  'Fetch.enable',
  'Page.addScriptToEvaluateOnNewDocument',
  'Page.navigate',
  'Page.reload',
  'Runtime.evaluate',
  'Fetch.continueRequest',
  'Fetch.failRequest',
]);
const safeBrowserSignals = new Set([
  'SIGABRT', 'SIGBUS', 'SIGFPE', 'SIGHUP', 'SIGILL', 'SIGINT', 'SIGKILL',
  'SIGPIPE', 'SIGQUIT', 'SIGSEGV', 'SIGTERM', 'SIGTRAP',
]);
const safeStderrCategories = new Set([
  'crash', 'devtools', 'error', 'gpu', 'other', 'sandbox',
]);
const fixedBrowserBinaryAllowlist = Object.freeze([
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/ms-playwright/chromium-1187/chrome-linux/chrome',
]);
let lastRunnerState = null;
let runnerOutputEmitted = false;

function createRunnerState() {
  return {
    run_started_at: new Date().toISOString(),
    run_ended_at: null,
    phase: 'startup',
    failure_reason: null,
    failure_phase: null,
    cdp_error: null,
    cdp_phase: null,
    cdp_command: null,
    browser_exit_code: null,
    browser_signal: null,
    stderr_line_count: 0,
    stderr_categories: new Set(),
  };
}

function boundedSafeTimestamp(value) {
  if (typeof value !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? value : null;
}

function recordRunnerFailure(state, reason, phase = state.phase, command = null) {
  if (safeRunnerPhases.has(phase)) state.phase = phase;
  const safeReason = safeRunnerFailureReasons.has(reason) ?
    reason : 'unknown_failure';
  if (state.failure_reason === null) state.failure_reason = safeReason;
  if (state.failure_phase === null && safeRunnerPhases.has(phase)) {
    state.failure_phase = phase;
  }
  if (safeReason.startsWith('cdp_') || safeReason.startsWith('pipe_')) {
    if (state.cdp_error === null) {
      state.cdp_error = safeReason;
      state.cdp_phase = safeRunnerPhases.has(phase) ? phase : null;
      state.cdp_command = safeCdpCommands.has(command) ? command : null;
    }
  }
}

function classifyPipeFailure(error) {
  const code = error && typeof error.code === 'string' ? error.code : '';
  if (code === 'ECONNRESET') return 'pipe_reset';
  if (code === 'EPIPE' || code === 'ERR_STREAM_DESTROYED') {
    return 'pipe_closed';
  }
  return 'pipe_error';
}

function noteBrowserStderr(state, data) {
  const text = Buffer.isBuffer(data) ? data.toString('utf8') : String(data);
  const boundedText = text.slice(0, 65536);
  const lineCount = boundedText.length ?
    boundedText.split(/\r?\n/).filter(Boolean).length : 0;
  state.stderr_line_count = Math.min(
    64, state.stderr_line_count + lineCount,
  );
  const categories = [
    [/crash|fatal|segmentation|abort|sig(?:abrt|segv)/i, 'crash'],
    [/devtools|remote debugging|debugging pipe/i, 'devtools'],
    [/gpu|gl|ozone/i, 'gpu'],
    [/sandbox|zygote|setuid/i, 'sandbox'],
    [/error|failed|cannot|unable/i, 'error'],
  ];
  for (const [pattern, category] of categories) {
    if (pattern.test(boundedText)) state.stderr_categories.add(category);
  }
  if (lineCount > 0 && state.stderr_categories.size === 0) {
    state.stderr_categories.add('other');
  }
}

function boundedRunnerDiagnostic(state) {
  if (!state || typeof state !== 'object') return null;
  const categories = state.stderr_categories instanceof Set ?
    [...state.stderr_categories] : [];
  const phase = state.cdp_phase || state.failure_phase || state.phase;
  const diagnostic = {
    run_started_at: boundedSafeTimestamp(state.run_started_at),
    run_ended_at: boundedSafeTimestamp(state.run_ended_at),
    phase: safeRunnerPhases.has(phase) ? phase : 'unknown',
    failure_reason: safeRunnerFailureReasons.has(state.failure_reason) ?
      state.failure_reason : null,
    cdp_error: safeRunnerFailureReasons.has(state.cdp_error) ?
      state.cdp_error : null,
    browser_exit_code: Number.isInteger(state.browser_exit_code) &&
      state.browser_exit_code >= 0 && state.browser_exit_code <= 255 ?
      state.browser_exit_code : null,
    browser_signal: safeBrowserSignals.has(state.browser_signal) ?
      state.browser_signal : null,
    stderr_line_count: Number.isInteger(state.stderr_line_count) &&
      state.stderr_line_count >= 0 && state.stderr_line_count <= 64 ?
      state.stderr_line_count : null,
    stderr_categories: categories.filter(category =>
      safeStderrCategories.has(category)).slice(0, 6),
  };
  if (safeCdpCommands.has(state.cdp_command)) {
    diagnostic.cdp_command = state.cdp_command;
  }
  return diagnostic;
}

class Cdp {
  constructor(
    child,
    onFailure = () => {},
    commandTimeoutMs = CDP_COMMAND_TIMEOUT_MS,
  ) {
    this.child = child;
    this.commandTimeoutMs = commandTimeoutMs;
    this.id = 0;
    this.pending = new Map();
    this.buffer = Buffer.alloc(0);
    this.onEvent = () => {};
    this.onFailure = onFailure;
    this.failure = null;
    this.closed = false;
    child.stdio[4].on('data', data => this.consume(data));
    child.stdio[4].on('error', error => {
      if (this.closed) return;
      this.reportFailure(classifyPipeFailure(error), error);
      this.close();
    });
    child.stdio[3].on('error', error => {
      if (this.closed) return;
      this.reportFailure(classifyPipeFailure(error), error);
      this.close();
    });
    child.on('error', error => {
      if (this.closed) return;
      this.reportFailure('child_error', error);
      this.close();
    });
    child.on('exit', (code, signal) => {
      if (!this.closed) {
        this.reportFailure(signal ? 'child_signal' : 'child_exit',
          {code, signal});
        this.close();
      }
    });
  }
  reportFailure(reason, error, command = null) {
    if (this.closed) return;
    if (this.failure === null) this.failure = reason;
    const pendingCommand = this.pending.values().next().value?.method || null;
    this.onFailure(reason, error, command || pendingCommand);
  }
  consume(data) {
    this.buffer = Buffer.concat([this.buffer, data]);
    let end;
    while ((end = this.buffer.indexOf(0)) !== -1) {
      const frame = this.buffer.subarray(0, end);
      this.buffer = this.buffer.subarray(end + 1);
      let message;
      try { message = JSON.parse(frame.toString('utf8')); }
      catch (_) {
        this.reportFailure('cdp_parse_error');
        this.close();
        return;
      }
      const pending = this.pending.get(message.id);
      if (pending) {
        this.pending.delete(message.id);
        clearTimeout(pending.timer);
        if (message.error) {
          this.reportFailure('cdp_error', null, pending.method);
          pending.reject(new Error('cdp_error'));
        }
        else pending.resolve(message.result || {});
      } else if (message.method) {
        this.onEvent(message);
      }
    }
  }
  command(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      if (this.closed) {
        reject(new Error(this.failure || 'cdp_closed'));
        return;
      }
      const id = ++this.id;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        this.reportFailure('cdp_timeout', null, method);
        reject(new Error('cdp_timeout'));
      }, this.commandTimeoutMs);
      this.pending.set(id, {resolve, reject, timer, method});
      const message = {id, method, params};
      if (sessionId) message.sessionId = sessionId;
      try {
        this.child.stdio[3].write(JSON.stringify(message) + '\0');
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        this.reportFailure(classifyPipeFailure(error), error);
        reject(new Error(this.failure || 'pipe_error'));
      }
    });
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error(this.failure || 'cdp_closed'));
    }
    this.pending.clear();
  }
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const ordinaryPrompt = '你好，今天過得如何？';
const mailPrompt = '把劉一帆的信件整理出來';
const syntheticMailPrompt = 'Organize the authorized synthetic mail evidence.';
const syntheticDocumentPrompt =
  'Find the acceptance condition in the authorized project document.';
const publicResponseStatuses = new Set([
  'complete', 'partial', 'clarification_required', 'error',
]);
const safePhases = new Set([
  'runtime_init', 'provider_model', 'provider_timeout', 'provider_request',
  'mcp_client', 'mcp_timeout', 'finalization', 'turn_budget', 'projection',
  'session_state', 'unknown',
]);
const providerStopReasons = new Set([
  'budget_exhausted', 'citation_validation_failed',
  'coverage_validation_failed', 'invalid_arguments', 'mcp_unavailable',
  'no_evidence', 'no_progress', 'provider_incomplete',
  'provider_timeout', 'public_term_unavailable',
]);
const safeMcpFailureReasonCodes = Object.freeze([
  'http_status',
  'jsonrpc_result_error',
  'missing_structured_payload',
  'missing_data_mapping',
  'authorization_audit_failed',
  'authentication_required',
  'forbidden_tool',
  'handler_not_configured',
  'invalid_tool_arguments',
  'required_grant_unavailable',
  'tool_execution_failed',
  'tool_policy_unavailable',
  'unknown_tool',
  'unsafe_tool_payload',
  'workspace_role_forbidden',
]);
const mcpFailureReasons = new Set([
  ...safeMcpFailureReasonCodes,
]);
const providerAttemptOutcomes = new Set([
  'completed', 'error', 'incomplete', 'invalid', 'timeout',
]);
const providerResponseStatuses = new Set([
  'completed', 'failed', 'incomplete', 'in_progress', 'queued', 'unknown',
]);
const citationProjectionResults = new Set([
  'empty', 'preserved', 'reduced', 'mcp_error', 'validation_rejected',
]);
const finalizationValidationResults = new Set([
  'passed', 'citation_rejected', 'coverage_rejected', 'parse_rejected',
  'provider_incomplete',
]);
const safeDiagnosticTools = new Set([
  'none', 'other', 'query_effective_graph_view', 'query_mail_evidence',
  'clarify_public_terminology',
]);
const safeProviderStatuses = new Set([
  'cancelled', 'completed', 'failed', 'incomplete',
]);
const safeProviderIncompleteReasons = new Set([
  'content_filter', 'max_output_tokens',
]);
const safeProviderErrorCodes = new Set([
  'authentication_error', 'conflict_error', 'invalid_request_error',
  'not_found_error', 'permission_error', 'rate_limit_error',
  'server_error', 'unprocessable_entity_error',
]);
const safeProviderErrorTypes = new Set([
  'api_error', 'authentication_error', 'invalid_request_error',
  'rate_limit_error', 'server_error',
]);
const safeProviderErrorParams = new Set([
  'model', 'tools', 'tool_choice', 'text.format', 'reasoning',
  'max_output_tokens', 'stream', 'store', 'safety_identifier',
]);
const safeProviderErrorMessageClasses = new Set([
  'timeout', 'rate_limit', 'capacity_unavailable', 'invalid_parameter',
  'unknown',
]);
const safeProviderBodyShapes = new Set([
  'empty', 'gzip_bytes', 'invalid_json', 'invalid_utf8', 'json_non_object',
  'json_object', 'sse', 'too_large',
]);
const safeProviderContentTypes = new Set([
  'application/json', 'application/problem+json', 'text/event-stream',
  'text/html', 'text/plain', 'other',
]);
const safeProviderContentEncodings = new Set([
  'br', 'deflate', 'gzip', 'identity', 'other',
]);
const safeMcpToolNames = new Set([
  'query_effective_graph',
  'query_effective_graph_view',
  'query_mail_evidence',
  'whoami',
]);
const safeMcpSelectorKinds = new Set([
  'none',
  'mail_import_session_id',
  'mail_evidence_bundle_id',
  'multiple',
]);
const safeMcpResponseStages = new Set([
  'request_built',
  'http_response',
  'jsonrpc_error',
  'structured_payload',
  'payload_validation',
  'payload_validated',
  'timeout',
  'exception',
]);

function boundedToken(value, maxLength = 96) {
  return typeof value === 'string' &&
    value.length > 0 && value.length <= maxLength &&
    /^[A-Za-z0-9_-]+$/.test(value) ? value : null;
}

function boundedMcpRequestShape(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const keys = [
    'request_contract_present',
    'table_query_present',
    'exact_field_present',
    'exact_inventory_kind_present',
    'page_size_present',
    'cursor_present',
  ];
  if (!keys.every(key => typeof value[key] === 'boolean')) return null;
  return Object.fromEntries(keys.map(key => [key, value[key]]));
}

function boundedMcpRequestDiscriminator(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  const toolName = value.tool_name;
  const selectorKind = value.selector_kind;
  const selectorPresent = value.selector_present;
  const selectorCount = value.selector_count;
  const selectorHash = value.selector_hash;
  const limit = value.limit;
  if (!safeMcpToolNames.has(toolName) ||
      !safeMcpSelectorKinds.has(selectorKind) ||
      typeof selectorPresent !== 'boolean' ||
      !Number.isInteger(selectorCount) || selectorCount < 0 ||
      selectorCount > 2 ||
      (selectorHash !== undefined && boundedHash(selectorHash) === null) ||
      (limit !== undefined &&
        (!Number.isInteger(limit) || limit < 1 || limit > 100))) {
    return null;
  }
  const safe = {
    tool_name: toolName,
    selector_kind: selectorKind,
    selector_present: selectorPresent,
    selector_count: selectorCount,
  };
  if (selectorHash !== undefined) safe.selector_hash = selectorHash;
  if (limit !== undefined) safe.limit = limit;
  return safe;
}

function boundedHash(value) {
  return typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value) ?
    value : null;
}

function parseExpectedEvidenceBindings(
  raw,
  requiredPhases = ['mail', 'document'],
) {
  if (typeof raw !== 'string' || raw.length === 0 || raw.length > 4096) {
    return null;
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (_) {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const bindings = {};
  const sourceFamilies = new Map([
    ['mail', 'mail'],
    ['document', 'document_text'],
  ]);
  if (!Array.isArray(requiredPhases) ||
      requiredPhases.length < 1 ||
      requiredPhases.some(phase => !sourceFamilies.has(phase))) {
    return null;
  }
  for (const phase of requiredPhases) {
    const sourceFamily = sourceFamilies.get(phase);
    const value = parsed[phase];
    if (!value || typeof value !== 'object' || Array.isArray(value) ||
        value.source_family !== sourceFamily ||
        !boundedHash(value.answer_fingerprint) ||
        !Array.isArray(value.citation_fingerprints) ||
        value.citation_fingerprints.length < 1 ||
        value.citation_fingerprints.length > 3 ||
        !value.citation_fingerprints.every(item => boundedHash(item))) {
      return null;
    }
    bindings[phase] = {
      source_family: sourceFamily,
      answer_fingerprint: value.answer_fingerprint,
      citation_fingerprints: value.citation_fingerprints.slice(),
    };
  }
  return bindings;
}

function normalizeOperatorDocumentPrompt(raw) {
  if (typeof raw !== 'string') return null;
  const prompt = raw.trim();
  return prompt.length >= 1 && prompt.length <= 4096 ? prompt : null;
}

function textFingerprint(value) {
  return typeof value === 'string' ?
    `sha256:${crypto.createHash('sha256').update(value, 'utf8').digest('hex')}` :
    null;
}

function boundedCount(value, maximum) {
  return Number.isInteger(value) && value >= 0 && value <= maximum ?
    value : null;
}

const safeTranscriptStatuses = new Set([
  'pending', 'complete', 'partial', 'clarification_required', 'error',
  'unknown',
]);

function boundedTranscriptShape(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const articleCount = boundedCount(value.article_count, 128);
  const assistantCount = boundedCount(value.assistant_count, 64);
  const pendingCount = boundedCount(value.pending_count, 64);
  const statuses = Array.isArray(value.assistant_statuses) &&
    value.assistant_statuses.length <= 64 &&
    value.assistant_statuses.every(status => safeTranscriptStatuses.has(status)) ?
    value.assistant_statuses.slice() : null;
  const citationCounts = Array.isArray(value.assistant_citation_counts) &&
    value.assistant_citation_counts.length <= 64 &&
    value.assistant_citation_counts.every(count => boundedCount(count, 100) !== null) ?
    value.assistant_citation_counts.slice() : null;
  const contentFingerprint = boundedHash(value.content_fingerprint);
  if (articleCount === null || assistantCount === null ||
      pendingCount === null || statuses === null || citationCounts === null ||
      contentFingerprint === null ||
      assistantCount > articleCount || pendingCount > articleCount ||
      statuses.length !== assistantCount ||
      citationCounts.length !== assistantCount) {
    return null;
  }
  const canonical = {
    article_count: articleCount,
    assistant_count: assistantCount,
    pending_count: pendingCount,
    assistant_statuses: statuses,
    assistant_citation_counts: citationCounts,
  };
  return {
    article_count: articleCount,
    assistant_count: assistantCount,
    pending_count: pendingCount,
    content_fingerprint: contentFingerprint,
    shape_hash: `sha256:${crypto.createHash('sha256')
      .update(JSON.stringify(canonical), 'utf8').digest('hex')}`,
  };
}

function boundedMcpStatus(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 64) {
    return null;
  }
  const normalized = value.toLowerCase();
  if (/^(?:not_found|pending_review|permission_denied|replan_required)$/.test(normalized)) {
    return normalized;
  }
  if (/^(?:ok|success|successful|completed)$/.test(normalized)) return 'ok';
  if (/^(?:mcp_)?(?:failed|failure|error|timeout|exception)$/.test(normalized)) {
    return 'error';
  }
  if (/^(?:denied|forbidden|unauthorized|authentication_required)$/.test(
    normalized,
  )) return 'denied';
  if (/^(?:in_progress|queued|pending)$/.test(normalized)) {
    return 'in_progress';
  }
  if (/^(?:request_built|http_response|jsonrpc_error|structured_payload|payload_validation|payload_validated)$/.test(normalized)) {
    return normalized;
  }
  return null;
}

function boundedElapsed(value, maximum = 60000) {
  return typeof value === 'number' && Number.isFinite(value) &&
    value >= 0 && value <= maximum ?
    Math.round(value * 1000) / 1000 : null;
}

function boundedCitationSnapshot(value) {
  if (!value || typeof value !== 'object') return null;
  const citationCount = boundedCount(value.citation_count, 100);
  const citationFingerprint = boundedHash(value.citation_fingerprint);
  return citationCount === null || citationFingerprint === null ? null : {
    citation_count: citationCount,
    citation_fingerprint: citationFingerprint,
  };
}

function boundedProviderSafeFields(value) {
  const source = value && typeof value === 'object' ? value : {};
  const safe = {};
  const allowlisted = [
    ['provider_status', safeProviderStatuses],
    ['incomplete_reason', safeProviderIncompleteReasons],
    ['provider_error_code', safeProviderErrorCodes],
    ['provider_error_type', safeProviderErrorTypes],
    ['provider_error_param', safeProviderErrorParams],
    ['provider_error_message_class', safeProviderErrorMessageClasses],
    ['response_body_shape', safeProviderBodyShapes],
    ['response_content_type', safeProviderContentTypes],
    ['response_content_encoding', safeProviderContentEncodings],
  ];
  for (const [key, allowed] of allowlisted) {
    if (allowed.has(source[key])) safe[key] = source[key];
  }
  for (const key of [
    'provider_status_sha256',
    'incomplete_reason_sha256',
    'provider_error_code_sha256',
    'provider_error_type_sha256',
    'response_content_type_sha256',
    'response_content_encoding_sha256',
  ]) {
    const hash = boundedHash(source[key]);
    if (hash !== null) safe[key] = hash;
  }
  for (const key of [
    'reasoning_item_present',
    'reasoning_encrypted_content_present',
    'response_declared_length_matches',
    'response_transfer_chunked',
    'formowl_halted',
    'final_repair_attempted',
  ]) {
    if (typeof source[key] === 'boolean') safe[key] = source[key];
  }
  for (const key of [
    'response_body_bytes',
    'response_declared_body_bytes',
    'formowl_attempts',
    'provider_attempt_count',
  ]) {
    const maximum = key.startsWith('response_') ? 4194305 :
      key === 'provider_attempt_count' ? MAX_PROVIDER_REQUESTS_PER_TURN : 3;
    const count = boundedCount(source[key], maximum);
    if (count !== null) safe[key] = count;
  }
  return safe;
}

function boundedProviderLoopDiagnostics(value) {
  if (!value || typeof value !== 'object') return {};
  const safe = {};
  if (Object.hasOwn(value, 'provider_attempts') ||
      Object.hasOwn(value, 'provider_attempt_count')) {
    const rawAttempts = Array.isArray(value.provider_attempts) ?
      value.provider_attempts : [];
    let attemptCount = boundedCount(
      value.provider_attempt_count,
      MAX_PROVIDER_REQUESTS_PER_TURN,
    );
    const tail = rawAttempts.slice(-MAX_PROVIDER_ATTEMPT_DIAGNOSTICS);
    let validTail = attemptCount !== null &&
      rawAttempts.length <= MAX_PROVIDER_REQUESTS_PER_TURN &&
      tail.length === Math.min(attemptCount, MAX_PROVIDER_ATTEMPT_DIAGNOSTICS) &&
      (rawAttempts.length === attemptCount ||
        rawAttempts.length === tail.length);
    const expectedFirstAttempt = attemptCount === null ?
      0 : attemptCount - tail.length + 1;
    const attempts = [];
    for (const [index, raw] of tail.entries()) {
      if (!raw || typeof raw !== 'object') {
        validTail = false;
        break;
      }
      const attempt = boundedCount(raw.attempt, MAX_PROVIDER_REQUESTS_PER_TURN);
      const elapsed = boundedElapsed(raw.elapsed_ms, MAX_UAT_TURN_MS);
      const choice = raw.tool_choice;
      const choiceKind = choice && choice.tool_choice;
      const selectedTool = choice && choice.selected_tool;
      const offeredToolCount = choice &&
        boundedCount(choice.offered_tool_count, 2);
      const offeredToolFingerprint = choice &&
        boundedHash(choice.offered_tool_fingerprint);
      if (attempt === null || elapsed === null ||
          !providerAttemptOutcomes.has(raw.outcome) ||
          !providerResponseStatuses.has(raw.response_status) ||
          boundedCount(raw.function_call_count, 3) === null ||
          !choice || !['none', 'auto', 'required_function', 'other']
            .includes(choiceKind) ||
          !safeDiagnosticTools.has(selectedTool) ||
          offeredToolCount === null || offeredToolFingerprint === null ||
          attempt !== expectedFirstAttempt + index) {
        validTail = false;
        break;
      }
      attempts.push({
        attempt,
        phase: 'provider_request',
        elapsed_ms: elapsed,
        outcome: raw.outcome,
        response_status: raw.response_status,
        function_call_count: raw.function_call_count,
        tool_choice: {
          tool_choice: choiceKind,
          selected_tool: selectedTool,
          offered_tool_count: offeredToolCount,
          offered_tool_fingerprint: offeredToolFingerprint,
        },
      });
    }
    safe.provider_attempts = validTail ? attempts : [];
    if (attemptCount !== null) safe.provider_attempt_count = attemptCount;
  }
  if (Array.isArray(value.mcp_citation_stages)) {
    const stages = value.mcp_citation_stages.slice(0, 3).flatMap(raw => {
      if (!raw || typeof raw !== 'object') return [];
      const callIndex = boundedCount(raw.call_index, 3);
      const elapsed = boundedElapsed(raw.elapsed_ms);
      const rawGoverned = boundedCitationSnapshot(raw.raw_governed);
      const compactedPresented = boundedCitationSnapshot(raw.compacted_presented);
      if (callIndex === null || elapsed === null ||
          rawGoverned === null || compactedPresented === null ||
          !citationProjectionResults.has(raw.projection_result)) {
        return [];
      }
      return [{
        call_index: callIndex,
        elapsed_ms: elapsed,
        raw_governed: rawGoverned,
        compacted_presented: compactedPresented,
        projection_result: raw.projection_result,
      }];
    });
    if (stages.length) safe.mcp_citation_stages = stages;
  }
  if (Object.hasOwn(value, 'finalization_validation')) {
    const rawValidations = Array.isArray(value.finalization_validation) ?
      value.finalization_validation : [];
    let validValidations = rawValidations.length <= 2;
    const validations = [];
    for (const raw of rawValidations) {
      if (!raw || typeof raw !== 'object') {
        validValidations = false;
        break;
      }
      const finalModel = boundedCitationSnapshot(raw.final_model);
      const availableGoverned = boundedCitationSnapshot(raw.available_governed);
      if (finalModel === null || availableGoverned === null ||
          !finalizationValidationResults.has(raw.validation_result) ||
          typeof raw.repair_attempted !== 'boolean') {
        validValidations = false;
        break;
      }
      validations.push({
        final_model: finalModel,
        available_governed: availableGoverned,
        validation_result: raw.validation_result,
        repair_attempted: raw.repair_attempted,
      });
    }
    safe.finalization_validation = validValidations ? validations : [];
  }
  return safe;
}

function boundedTimingList(value) {
  if (!Array.isArray(value)) return [];
  return value.slice(-MAX_PROVIDER_ATTEMPT_DIAGNOSTICS).flatMap(timing => {
    if (!timing || typeof timing !== 'object') return [];
    const phase = timing.phase;
    const elapsed = timing.elapsed_ms;
    if (!safePhases.has(phase) || typeof elapsed !== 'number' ||
        !Number.isFinite(elapsed) || elapsed < 0 || elapsed > 120000) {
      return [];
    }
    return [{phase, elapsed_ms: Math.round(elapsed * 1000) / 1000}];
  });
}

function boundedDiagnostic(diagnostic, body, citations) {
  const source = diagnostic && typeof diagnostic === 'object' ? diagnostic : {};
  const mcpSource = source.mcp && typeof source.mcp === 'object' ?
    source.mcp : null;
  let mcp = null;
  if (mcpSource) {
    const callCount = mcpSource.call_count;
    const elapsed = mcpSource.elapsed_ms;
    const statuses = mcpSource.status;
    const safeStatuses = Array.isArray(statuses) ?
      statuses.map(boundedMcpStatus) : [];
    const timeout = mcpSource.timeout;
    if (Number.isInteger(callCount) && callCount >= 0 && callCount <= 3 &&
        typeof elapsed === 'number' && Number.isFinite(elapsed) &&
        elapsed >= 0 && elapsed <= 120000 && Array.isArray(statuses) &&
        statuses.length <= 3 && safeStatuses.every(status => status !== null) &&
        typeof timeout === 'boolean') {
      const failureReason = mcpSource.failure_reason;
      mcp = {
        call_count: callCount,
        elapsed_ms: Math.round(elapsed * 1000) / 1000,
        status: safeStatuses,
        timeout,
        failure_reason: mcpFailureReasons.has(failureReason) ?
          failureReason : null,
        exception_class: boundedToken(mcpSource.exception_class, 64),
        request_shape: boundedMcpRequestShape(mcpSource.request_shape),
      };
      const requestDiscriminator = boundedMcpRequestDiscriminator(
        mcpSource.request_discriminator,
      );
      if (requestDiscriminator !== null) {
        mcp.request_discriminator = requestDiscriminator;
      }
      if (safeMcpResponseStages.has(mcpSource.response_stage)) {
        mcp.response_stage = mcpSource.response_stage;
      }
    }
  }
  const providerLoop = boundedProviderLoopDiagnostics(source);
  const providerTimings = Array.isArray(providerLoop.provider_attempts) &&
    providerLoop.provider_attempts.length ?
    providerLoop.provider_attempts.map(item => ({
      phase: item.phase,
      elapsed_ms: item.elapsed_ms,
    })) : boundedTimingList(source.provider_phase_timings);
  const output = {
    ...boundedProviderSafeFields(source),
    response_status: publicResponseStatuses.has(body.status) ?
      body.status : null,
    reason_code: boundedToken(source.reason_code) ||
      boundedToken(source.failure_class, 64),
    phase: safePhases.has(source.phase) ? source.phase : null,
    stop_reason: providerStopReasons.has(source.stop_reason) ?
      source.stop_reason : null,
    provider_phase_timings: providerTimings,
    mcp,
    payload_citation_count: Array.isArray(citations) &&
      citations.length <= 1000 ? citations.length : null,
  };
  Object.assign(output, providerLoop);
  return output;
}

// This runs inside the page. It observes clones, never replaces responses.
function installProbe() {
  const probe = {chat: [], transcript: null};
  window.__formowlUatProbe = probe;
  const original = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const started = performance.now();
    const input = args[0];
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const response = await original(...args);
    if (url.origin === location.origin &&
        ['/api/chat', '/api/transcript'].includes(url.pathname)) {
      response.clone().json().then(payload => {
        if (url.pathname === '/api/transcript') {
          probe.transcript = {
            ok: response.ok && Array.isArray(payload.turns),
            count: Array.isArray(payload.turns) ? payload.turns.length : null,
          };
        } else {
          // Kept only inside this fresh browser, never sent over CDP or logged.
          probe.chat.push({payload, http: response.status,
            elapsed: Math.round(performance.now() - started)});
        }
      }).catch(() => {
        if (url.pathname === '/api/chat') {
          probe.chat.push({payload: {}, http: response.status,
            elapsed: Math.round(performance.now() - started)});
        } else probe.transcript = {ok: false, count: null};
      });
    }
    return response;
  };
}

// Conservative visible-text assertions, NOT application routing rules.
function classify(
  phase,
  record,
  turn,
  {sourceNeutral = false, expectedEvidenceBinding = null} = {},
) {
  // This function is serialized into the page with classify.toString().
  // Keep all page-side validation local; it must not capture Node helpers.
  const MAX_PROVIDER_ATTEMPT_DIAGNOSTICS = 3;
  const MAX_PROVIDER_REQUESTS_PER_TURN = 3 + 1 + 2;
  const MAX_UAT_TURN_MS = 120000;
  const payload = record.payload || {};
  const body = payload.response || payload;
  const diagnostic = payload.diagnostic || body.diagnostic || {};
  const mcp = diagnostic.mcp || {};
  const toolCount = Number.isInteger(mcp.call_count) &&
    mcp.call_count >= 0 && mcp.call_count <= 3 ? mcp.call_count : null;
  const citations = Array.isArray(body.citations) ? body.citations : [];
  const citationLabels = Array.isArray(turn.citation_labels) ?
    turn.citation_labels : [];
  const citationProjectionMatches =
    citationLabels.length === citations.length &&
    citations.every((citation, index) => citation === citationLabels[index]);
  const safeFingerprint = value => typeof value === 'string' &&
    /^sha256:[0-9a-f]{64}$/.test(value);
  const sourceFamily = phase === 'mail' ? 'mail' :
    phase === 'document' ? 'document_text' : null;
  const sourceBindingRequired = sourceNeutral || phase === 'document';
  const actualCitationFingerprints = Array.isArray(turn.citation_fingerprints) ?
    turn.citation_fingerprints : [];
  const expectedCitationFingerprints = expectedEvidenceBinding &&
    Array.isArray(expectedEvidenceBinding.citation_fingerprints) ?
    expectedEvidenceBinding.citation_fingerprints : [];
  const sourceBindingVerified = !sourceBindingRequired || (
    sourceFamily !== null && expectedEvidenceBinding &&
    expectedEvidenceBinding.source_family === sourceFamily &&
    safeFingerprint(turn.answer_fingerprint) &&
    turn.answer_fingerprint === expectedEvidenceBinding.answer_fingerprint &&
    actualCitationFingerprints.length === citations.length &&
    actualCitationFingerprints.every(item => safeFingerprint(item)) &&
    actualCitationFingerprints.length === expectedCitationFingerprints.length &&
    actualCitationFingerprints.every((item, index) =>
      item === expectedCitationFingerprints[index])
  );
  const governedCitations = citations.length > 0 &&
    citationProjectionMatches &&
    sourceBindingVerified &&
    citations.every(citation => {
      if (typeof citation !== 'string') return false;
      if (sourceNeutral) {
        return /^(?:mailcitation_[0-9a-f]{24}|sha256:[0-9a-f]{64})$/
          .test(citation);
      }
      if (phase === 'document') return /^sha256:[0-9a-f]{64}$/.test(citation);
      return /^mailcitation_[0-9a-f]{24}$/.test(citation);
    });
  const providerErrorParams = new Set([
    'model', 'tools', 'tool_choice', 'text.format', 'reasoning',
    'max_output_tokens', 'stream', 'store', 'safety_identifier',
  ]);
  const providerErrorMessageClasses = new Set([
    'timeout', 'rate_limit', 'capacity_unavailable', 'invalid_parameter',
    'unknown',
  ]);
  const providerBodyShapes = new Set([
    'empty', 'gzip_bytes', 'invalid_json', 'invalid_utf8', 'json_non_object',
    'json_object', 'sse', 'too_large',
  ]);
  const safeProviderFields = {};
  if (providerErrorParams.has(diagnostic.provider_error_param)) {
    safeProviderFields.provider_error_param = diagnostic.provider_error_param;
  }
  if (providerErrorMessageClasses.has(diagnostic.provider_error_message_class)) {
    safeProviderFields.provider_error_message_class =
      diagnostic.provider_error_message_class;
  }
  if (providerBodyShapes.has(diagnostic.response_body_shape)) {
    safeProviderFields.response_body_shape = diagnostic.response_body_shape;
  }
  const noData = /沒有(?:找到|查到|任何|.*(?:資料|信件|郵件|文件|文檔))|查無|找不到.*(?:資料|信件|郵件|文件|文檔)|無相關(?:資料|信件|郵件|文件|文檔)|no (?:data|results|mail|messages|document|file)|(?:no|zero) matching/i;
  const operational = /未完成|失敗|逾時|超時|尚未準備|稍後再試|暫時無法|(?:provider|mcp|service|query|request).*(?:fail|error|unavailable|timeout)|timed? out|try again/i;
  const forbidden = /\/(?:home|tmp|run|workspace|var)\//i;
  const visible = turn.visible && Boolean(turn.text.trim()) &&
    !forbidden.test(turn.text + turn.error);
  const successful = record.http === 200 &&
    ['complete', 'partial'].includes(body.status) && turn.status === body.status;
  const mcpStatusHasFailure = Array.isArray(mcp.status) &&
    mcp.status.some(status => typeof status === 'string' &&
      /(?:fail|failure|error|timeout|exception|denied|forbidden|unauthori[sz]ed|unavailable|rejected)/i
        .test(status));
  const mcpSuccessShape = toolCount !== null && toolCount > 0 &&
    Array.isArray(mcp.status) && mcp.status.length === toolCount &&
    mcp.status.every(status => typeof status === 'string' &&
      /^(?:ok|success|successful|completed)$/i
        .test(status)) &&
    mcp.timeout === false && !mcp.failure_reason && !mcp.exception_class;
  const citationSnapshotIsValid = snapshot => snapshot &&
    typeof snapshot === 'object' &&
    Number.isInteger(snapshot.citation_count) &&
    snapshot.citation_count >= 0 && snapshot.citation_count <= 100 &&
    typeof snapshot.citation_fingerprint === 'string' &&
    /^sha256:[0-9a-f]{64}$/.test(snapshot.citation_fingerprint);
  const finalizationResults = new Set([
    'passed', 'citation_rejected', 'coverage_rejected', 'parse_rejected',
    'provider_incomplete',
  ]);
  const rawFinalizations = diagnostic.finalization_validation;
  const latestFinalization = Array.isArray(rawFinalizations) &&
    rawFinalizations.length >= 1 && rawFinalizations.length <= 2 ?
    rawFinalizations.at(-1) : null;
  const latestFinalizationIsValid = Boolean(latestFinalization &&
    typeof latestFinalization === 'object' &&
    citationSnapshotIsValid(latestFinalization.final_model) &&
    citationSnapshotIsValid(latestFinalization.available_governed) &&
    finalizationResults.has(latestFinalization.validation_result) &&
    typeof latestFinalization.repair_attempted === 'boolean');
  const providerFinalizationPassed =
    !['mail', 'document'].includes(phase) || sourceNeutral ||
    Boolean(latestFinalizationIsValid &&
      latestFinalization.validation_result === 'passed' &&
      latestFinalization.final_model.citation_count > 0);
  const rawProviderAttempts = diagnostic.provider_attempts;
  const hasProviderAttempts = Object.hasOwn(diagnostic, 'provider_attempts');
  const hasRawProviderAttemptCount = Object.hasOwn(
    diagnostic, 'provider_attempt_count',
  );
  const providerAttemptCount = hasRawProviderAttemptCount ?
    diagnostic.provider_attempt_count : null;
  const hasProviderAttemptCount = hasRawProviderAttemptCount;
  const providerAttemptResults = new Set([
    'completed', 'error', 'incomplete', 'invalid', 'timeout',
  ]);
  const providerAttemptStatuses = new Set([
    'completed', 'failed', 'incomplete', 'in_progress', 'queued', 'unknown',
  ]);
  const providerAttemptTools = new Set([
    'none', 'other', 'query_effective_graph_view', 'query_mail_evidence',
    'clarify_public_terminology',
  ]);
  const latestProviderAttempt = Array.isArray(rawProviderAttempts) &&
    rawProviderAttempts.length >= 1 &&
    rawProviderAttempts.length <= MAX_PROVIDER_ATTEMPT_DIAGNOSTICS ?
    rawProviderAttempts.at(-1) : null;
  const providerAttemptTailIsValid = Number.isInteger(providerAttemptCount) &&
    providerAttemptCount >= 1 &&
    providerAttemptCount <= MAX_PROVIDER_REQUESTS_PER_TURN &&
    Array.isArray(rawProviderAttempts) &&
    rawProviderAttempts.length ===
      Math.min(providerAttemptCount, MAX_PROVIDER_ATTEMPT_DIAGNOSTICS) &&
    rawProviderAttempts.every((attempt, index) =>
      attempt && attempt.attempt ===
        providerAttemptCount - rawProviderAttempts.length + index + 1);
  const latestProviderAttemptIsValid = (() => {
    const choice = latestProviderAttempt && latestProviderAttempt.tool_choice;
    return Boolean(latestProviderAttempt &&
      typeof latestProviderAttempt === 'object' &&
      Number.isInteger(latestProviderAttempt.attempt) &&
      latestProviderAttempt.attempt >= 0 &&
      latestProviderAttempt.attempt <= MAX_PROVIDER_REQUESTS_PER_TURN &&
      typeof latestProviderAttempt.elapsed_ms === 'number' &&
      Number.isFinite(latestProviderAttempt.elapsed_ms) &&
      latestProviderAttempt.elapsed_ms >= 0 &&
      latestProviderAttempt.elapsed_ms <= MAX_UAT_TURN_MS &&
      providerAttemptResults.has(latestProviderAttempt.outcome) &&
      providerAttemptStatuses.has(latestProviderAttempt.response_status) &&
      Number.isInteger(latestProviderAttempt.function_call_count) &&
      latestProviderAttempt.function_call_count >= 0 &&
      latestProviderAttempt.function_call_count <= 3 &&
      choice &&
      ['none', 'auto', 'required_function', 'other']
        .includes(choice.tool_choice) &&
      providerAttemptTools.has(choice.selected_tool) &&
      Number.isInteger(choice.offered_tool_count) &&
      choice.offered_tool_count >= 0 && choice.offered_tool_count <= 2 &&
      typeof choice.offered_tool_fingerprint === 'string' &&
      /^sha256:[0-9a-f]{64}$/.test(choice.offered_tool_fingerprint));
  })();
  const providerCompleted = phase === 'document' && !sourceNeutral ?
    Boolean(hasProviderAttempts && hasProviderAttemptCount &&
      providerAttemptTailIsValid && latestProviderAttemptIsValid &&
      latestProviderAttempt.outcome === 'completed' &&
      latestProviderAttempt.response_status === 'completed') :
    phase !== 'mail' || sourceNeutral ||
      (!hasProviderAttempts && !hasProviderAttemptCount) ||
      Boolean(hasProviderAttempts && hasProviderAttemptCount &&
        providerAttemptTailIsValid && latestProviderAttemptIsValid &&
        latestProviderAttempt.outcome === 'completed' &&
        latestProviderAttempt.response_status === 'completed');
  const providerFailure = ['mail', 'document'].includes(phase) &&
    (diagnostic.reason_code === 'provider_finalization_failed' ||
      ['provider_incomplete', 'provider_timeout']
        .includes(diagnostic.stop_reason));
  const hasFailure = record.http >= 400 || body.status === 'error' ||
    Boolean(diagnostic.failure_class) || providerFailure ||
    mcp.timeout === true ||
    mcpStatusHasFailure ||
    (toolCount > 0 && (Boolean(mcp.failure_reason) ||
      Boolean(mcp.exception_class)));
  let pass = false;
  let status = phase + '_failed';
  if (phase === 'ordinary') {
    const conversational = /你好|您好|嗨|謝謝|高興|開心|很好|不錯|準備|隨時|hello|hi\b|hey\b|doing (?:well|fine|great)|happy to help|ready to help/i.test(turn.text);
    pass = visible && successful && body.status === 'complete' &&
      !hasFailure && toolCount === 0 && turn.citations === 0 &&
      citations.length === 0 && citationLabels.length === 0 &&
      turn.text === body.answer.trim() &&
      conversational && !noData.test(turn.text) && !operational.test(turn.text) &&
      !turn.error;
    if (pass) status = 'ordinary_passed';
  } else if (hasFailure) {
    // An explicit operational failure is safe reporting, NOT a passed UAT.
    pass = visible && turn.status === 'error' &&
      operational.test(turn.text + turn.error) &&
      !noData.test(turn.text + turn.error) && turn.citations === 0;
    status = pass ? `${phase}_operational_failure` :
      `${phase}_unsafe_failure`;
  } else {
    pass = visible && successful && mcpSuccessShape &&
      turn.citations > 0 && governedCitations &&
      turn.citations === citations.length &&
      turn.text === body.answer.trim() && !turn.error &&
      providerFinalizationPassed && providerCompleted &&
      (body.status !== 'partial' || turn.incomplete_visible === true) &&
      // Structured provider/finalization outcomes govern acceptance. A cited
      // business statement may itself contain operational-sounding wording.
      !noData.test(turn.text);
    if (pass) {
      status = sourceNeutral ? 'source_neutral_cited_result' :
        `${phase}_cited_result`;
    }
  }
  return {status, http_status: record.http, tool_count: toolCount,
    citation_count: turn.citations, elapsed_ms: record.elapsed,
    visible_text_pass: Boolean(pass),
    source_binding_verified: sourceNeutral ? sourceBindingVerified : null,
    diagnostic: (() => {
      const responseStatuses = new Set([
        'complete', 'partial', 'clarification_required', 'error',
      ]);
      const phases = new Set([
        'runtime_init', 'provider_model', 'provider_timeout',
        'provider_request', 'mcp_client', 'mcp_timeout', 'finalization',
        'turn_budget', 'projection', 'session_state', 'unknown',
      ]);
      const stopReasons = new Set([
        'budget_exhausted', 'citation_validation_failed',
        'coverage_validation_failed', 'invalid_arguments', 'mcp_unavailable',
        'no_evidence', 'no_progress', 'provider_incomplete',
        'provider_timeout', 'public_term_unavailable',
      ]);
      const failureReasons = new Set([
        'http_status',
        'jsonrpc_result_error',
        'missing_structured_payload',
        'missing_data_mapping',
        'authorization_audit_failed',
        'authentication_required',
        'forbidden_tool',
        'handler_not_configured',
        'invalid_tool_arguments',
        'required_grant_unavailable',
        'tool_execution_failed',
        'tool_policy_unavailable',
        'unknown_tool',
        'unsafe_tool_payload',
        'workspace_role_forbidden',
      ]);
      const token = (value, maxLength = 96) =>
        typeof value === 'string' && value.length > 0 &&
        value.length <= maxLength && /^[A-Za-z0-9_-]+$/.test(value) ?
          value : null;
      const timings = Array.isArray(diagnostic.provider_phase_timings) ?
        diagnostic.provider_phase_timings
          .slice(-MAX_PROVIDER_ATTEMPT_DIAGNOSTICS).flatMap(timing => {
          if (!timing || typeof timing !== 'object') return [];
          const elapsed = timing.elapsed_ms;
          if (!phases.has(timing.phase) || typeof elapsed !== 'number' ||
              !Number.isFinite(elapsed) || elapsed < 0 || elapsed > 120000) {
            return [];
          }
          return [{phase: timing.phase,
            elapsed_ms: Math.round(elapsed * 1000) / 1000}];
        }) : [];
      const mcpSource = diagnostic.mcp &&
        typeof diagnostic.mcp === 'object' ? diagnostic.mcp : null;
      let safeMcp = null;
      if (mcpSource) {
        const statuses = mcpSource.status;
        const elapsed = mcpSource.elapsed_ms;
        const requestShapeValue = mcpSource.request_shape;
        const requestShapeKeys = [
          'request_contract_present',
          'table_query_present',
          'exact_field_present',
          'exact_inventory_kind_present',
          'page_size_present',
          'cursor_present',
        ];
        const requestShape = requestShapeValue &&
          typeof requestShapeValue === 'object' &&
          !Array.isArray(requestShapeValue) &&
          requestShapeKeys.every(key => typeof requestShapeValue[key] === 'boolean') ?
          Object.fromEntries(
            requestShapeKeys.map(key => [key, requestShapeValue[key]]),
          ) : null;
        const mcpToolNames = new Set([
          'query_effective_graph',
          'query_effective_graph_view',
          'query_mail_evidence',
          'whoami',
        ]);
        const mcpSelectorKinds = new Set([
          'none',
          'mail_import_session_id',
          'mail_evidence_bundle_id',
          'multiple',
        ]);
        const mcpResponseStages = new Set([
          'request_built',
          'http_response',
          'jsonrpc_error',
          'structured_payload',
          'payload_validation',
          'payload_validated',
          'timeout',
          'exception',
        ]);
        const rawDiscriminator = mcpSource.request_discriminator;
        let requestDiscriminator = null;
        if (rawDiscriminator && typeof rawDiscriminator === 'object' &&
            !Array.isArray(rawDiscriminator)) {
          const selectorHash = rawDiscriminator.selector_hash;
          const rawLimit = rawDiscriminator.limit;
          const validHash = selectorHash === undefined ||
            (typeof selectorHash === 'string' &&
              /^sha256:[0-9a-f]{64}$/.test(selectorHash));
          const validLimit = rawLimit === undefined ||
            (Number.isInteger(rawLimit) && rawLimit >= 1 && rawLimit <= 100);
          if (mcpToolNames.has(rawDiscriminator.tool_name) &&
              mcpSelectorKinds.has(rawDiscriminator.selector_kind) &&
              typeof rawDiscriminator.selector_present === 'boolean' &&
              Number.isInteger(rawDiscriminator.selector_count) &&
              rawDiscriminator.selector_count >= 0 &&
              rawDiscriminator.selector_count <= 2 &&
              validHash && validLimit) {
            requestDiscriminator = {
              tool_name: rawDiscriminator.tool_name,
              selector_kind: rawDiscriminator.selector_kind,
              selector_present: rawDiscriminator.selector_present,
              selector_count: rawDiscriminator.selector_count,
            };
            if (selectorHash !== undefined) {
              requestDiscriminator.selector_hash = selectorHash;
            }
            if (rawLimit !== undefined) requestDiscriminator.limit = rawLimit;
          }
        }
        if (Number.isInteger(mcpSource.call_count) &&
            mcpSource.call_count >= 0 && mcpSource.call_count <= 3 &&
            typeof elapsed === 'number' && Number.isFinite(elapsed) &&
            elapsed >= 0 && elapsed <= 120000 && Array.isArray(statuses) &&
            statuses.length <= 3 &&
            statuses.every(item => token(item, 64)) &&
            typeof mcpSource.timeout === 'boolean') {
          safeMcp = {
            call_count: mcpSource.call_count,
            elapsed_ms: Math.round(elapsed * 1000) / 1000,
            status: statuses.slice(),
            timeout: mcpSource.timeout,
            failure_reason: failureReasons.has(mcpSource.failure_reason) ?
              mcpSource.failure_reason : null,
            exception_class: token(mcpSource.exception_class, 64),
            request_shape: requestShape,
          };
          if (requestDiscriminator !== null) {
            safeMcp.request_discriminator = requestDiscriminator;
          }
          if (mcpResponseStages.has(mcpSource.response_stage)) {
            safeMcp.response_stage = mcpSource.response_stage;
          }
        }
      }
      const loopOutcomes = new Set([
        'completed', 'error', 'incomplete', 'invalid', 'timeout',
      ]);
      const loopResponseStatuses = new Set([
        'completed', 'failed', 'incomplete', 'in_progress', 'queued', 'unknown',
      ]);
      const loopProjectionResults = new Set([
        'empty', 'preserved', 'reduced', 'mcp_error', 'validation_rejected',
      ]);
      const loopValidationResults = new Set([
        'passed', 'citation_rejected', 'coverage_rejected', 'parse_rejected',
        'provider_incomplete',
      ]);
      const loopTools = new Set([
        'none', 'other', 'query_effective_graph_view', 'query_mail_evidence',
        'clarify_public_terminology',
      ]);
      const hash = value => typeof value === 'string' &&
        /^sha256:[0-9a-f]{64}$/.test(value) ? value : null;
      const count = (value, maximum) => Number.isInteger(value) &&
        value >= 0 && value <= maximum ? value : null;
      const elapsed = (value, maximum = 60000) => typeof value === 'number' &&
        Number.isFinite(value) && value >= 0 && value <= maximum ?
        Math.round(value * 1000) / 1000 : null;
      const snapshot = value => {
        if (!value || typeof value !== 'object') return null;
        const citationCount = count(value.citation_count, 100);
        const citationFingerprint = hash(value.citation_fingerprint);
        return citationCount === null || citationFingerprint === null ? null : {
          citation_count: citationCount,
          citation_fingerprint: citationFingerprint,
        };
      };
      const loopDiagnostics = {};
      if (Object.hasOwn(diagnostic, 'provider_attempts') ||
          Object.hasOwn(diagnostic, 'provider_attempt_count')) {
        const rawAttempts = Array.isArray(diagnostic.provider_attempts) ?
          diagnostic.provider_attempts : [];
        let attemptCount = count(
          diagnostic.provider_attempt_count,
          MAX_PROVIDER_REQUESTS_PER_TURN,
        );
        const tail = rawAttempts.slice(-MAX_PROVIDER_ATTEMPT_DIAGNOSTICS);
        let validTail = attemptCount !== null &&
          rawAttempts.length <= MAX_PROVIDER_REQUESTS_PER_TURN &&
          tail.length === Math.min(
            attemptCount,
            MAX_PROVIDER_ATTEMPT_DIAGNOSTICS,
          ) &&
          (rawAttempts.length === attemptCount ||
            rawAttempts.length === tail.length);
        const expectedFirstAttempt = attemptCount === null ?
          0 : attemptCount - tail.length + 1;
        const attempts = [];
        for (const [index, raw] of tail.entries()) {
          if (!raw || typeof raw !== 'object') {
            validTail = false;
            break;
          }
          const attempt = count(raw.attempt, MAX_PROVIDER_REQUESTS_PER_TURN);
          const attemptElapsed = elapsed(raw.elapsed_ms, MAX_UAT_TURN_MS);
          const choice = raw.tool_choice;
          const choiceKind = choice && choice.tool_choice;
          const selectedTool = choice && choice.selected_tool;
          const offeredToolCount = choice &&
            count(choice.offered_tool_count, 2);
          const offeredToolFingerprint = choice &&
            hash(choice.offered_tool_fingerprint);
          if (attempt === null || attemptElapsed === null ||
              !loopOutcomes.has(raw.outcome) ||
              !loopResponseStatuses.has(raw.response_status) ||
              count(raw.function_call_count, 3) === null ||
              !choice || !['none', 'auto', 'required_function', 'other']
                .includes(choiceKind) ||
              !loopTools.has(selectedTool) || offeredToolCount === null ||
              offeredToolFingerprint === null ||
              attempt !== expectedFirstAttempt + index) {
            validTail = false;
            break;
          }
          attempts.push({
            attempt,
            phase: 'provider_request',
            elapsed_ms: attemptElapsed,
            outcome: raw.outcome,
            response_status: raw.response_status,
            function_call_count: raw.function_call_count,
            tool_choice: {
              tool_choice: choiceKind,
              selected_tool: selectedTool,
              offered_tool_count: offeredToolCount,
              offered_tool_fingerprint: offeredToolFingerprint,
            },
          });
        }
        loopDiagnostics.provider_attempts = validTail ? attempts : [];
        if (attemptCount !== null) {
          loopDiagnostics.provider_attempt_count = attemptCount;
        }
      }
      if (Array.isArray(diagnostic.mcp_citation_stages)) {
        const stages = diagnostic.mcp_citation_stages.slice(0, 3).flatMap(raw => {
          if (!raw || typeof raw !== 'object') return [];
          const callIndex = count(raw.call_index, 3);
          const stageElapsed = elapsed(raw.elapsed_ms);
          const rawGoverned = snapshot(raw.raw_governed);
          const compactedPresented = snapshot(raw.compacted_presented);
          if (callIndex === null || stageElapsed === null ||
              rawGoverned === null || compactedPresented === null ||
              !loopProjectionResults.has(raw.projection_result)) {
            return [];
          }
          return [{
            call_index: callIndex,
            elapsed_ms: stageElapsed,
            raw_governed: rawGoverned,
            compacted_presented: compactedPresented,
            projection_result: raw.projection_result,
          }];
        });
        if (stages.length) loopDiagnostics.mcp_citation_stages = stages;
      }
      if (Object.hasOwn(diagnostic, 'finalization_validation')) {
        const rawValidations = Array.isArray(diagnostic.finalization_validation) ?
          diagnostic.finalization_validation : [];
        let validValidations = rawValidations.length <= 2;
        const validations = [];
        for (const raw of rawValidations) {
            if (!raw || typeof raw !== 'object') {
              validValidations = false;
              break;
            }
            const finalModel = snapshot(raw.final_model);
            const availableGoverned = snapshot(raw.available_governed);
            if (finalModel === null || availableGoverned === null ||
                !loopValidationResults.has(raw.validation_result) ||
                typeof raw.repair_attempted !== 'boolean') {
              validValidations = false;
              break;
            }
            validations.push({
              final_model: finalModel,
              available_governed: availableGoverned,
              validation_result: raw.validation_result,
              repair_attempted: raw.repair_attempted,
            });
        }
        loopDiagnostics.finalization_validation =
          validValidations ? validations : [];
      }
      const providerTimings = Array.isArray(loopDiagnostics.provider_attempts) &&
        loopDiagnostics.provider_attempts.length ?
        loopDiagnostics.provider_attempts.map(item => ({
          phase: item.phase,
          elapsed_ms: item.elapsed_ms,
        })) : timings;
      return {
        response_status: responseStatuses.has(body.status) ? body.status : null,
        reason_code: token(diagnostic.reason_code) ||
          token(diagnostic.failure_class, 64),
        phase: phases.has(diagnostic.phase) ? diagnostic.phase : null,
        stop_reason: stopReasons.has(diagnostic.stop_reason) ?
          diagnostic.stop_reason : null,
        provider_phase_timings: providerTimings,
        mcp: safeMcp,
        payload_citation_count: Array.isArray(citations) &&
          citations.length <= 1000 ? citations.length : null,
        ...safeProviderFields,
        ...loopDiagnostics,
      };
    })()};
}

function safeOutput(result, {final = false} = {}) {
  const runnerState = result && result.runner_diagnostic &&
    typeof result.runner_diagnostic === 'object' ?
    result.runner_diagnostic : null;
  if (final && runnerState && runnerState.run_ended_at === null) {
    runnerState.run_ended_at = new Date().toISOString();
  }
  runnerOutputEmitted = true;
  // Never serialize provider data, exceptions, page text, URLs or credentials.
  const allowed = new Set([
    'ordinary_failed', 'ordinary_passed', 'ordinary_timeout',
    'mail_failed', 'mail_timeout', 'mail_operational_failure',
    'mail_unsafe_failure', 'mail_cited_result', 'runner_error',
    'document_failed', 'document_timeout', 'document_operational_failure',
    'document_unsafe_failure', 'document_cited_result',
    'source_neutral_failed', 'source_neutral_timeout',
    'source_neutral_cited_result', 'source_neutral_passed',
    'page_not_ready', 'auth_required', 'session_not_fresh',
    'acceptance_followups_failed', 'acceptance_followups_passed',
    'basic_only_failed', 'basic_only_timeout', 'basic_only_passed',
    'awaiting_master_go', 'tooling_self_check_passed',
  ]);
  const output = {status: allowed.has(result.status) ? result.status : 'runner_error'};
  if (result.acceptance_surface === 'basic_only') {
    output.acceptance_surface = 'basic_only';
    output.mail_acceptance = 'not_run';
    output.ordinary_mcp_zero = result.ordinary_mcp_zero === true;
  }
  if (result.acceptance_surface === 'source_neutral_synthetic') {
    output.acceptance_surface = 'source_neutral_synthetic';
    output.mail_acceptance = 'synthetic_only';
    output.document_acceptance = 'synthetic_only';
    output.provider_finalization =
      result.provider_finalization === 'not_exercised_provider_free' ?
        result.provider_finalization : null;
    output.ordinary_mcp_zero = result.ordinary_mcp_zero === true;
  }
  for (const key of [
    'http_status', 'tool_count', 'citation_count', 'elapsed_ms',
    'mail_tool_count', 'mail_citation_count',
    'document_tool_count', 'document_citation_count',
  ]) {
    if (Object.hasOwn(result, key)) {
      const upperBound = key === 'http_status' ? 599 : 180000;
      const lowerBound = key === 'http_status' ? 100 : 0;
      output[key] = Number.isFinite(result[key]) &&
        result[key] >= lowerBound && result[key] <= upperBound ?
        result[key] : null;
    }
  }
  for (const key of [
    'reload_transcript_count', 'reset_transcript_count',
    'post_reset_transcript_count', 'pre_reload_visible_turn_count',
    'reload_visible_turn_count', 'reload_visible_pending_count',
    'reset_visible_article_count', 'reset_visible_turn_count',
    'post_reset_visible_turn_count', 'post_reset_visible_pending_count',
  ]) {
    if (Object.hasOwn(result, key)) {
      const maximum = key === 'reset_visible_article_count' ? 128 : 64;
      output[key] = Number.isInteger(result[key]) && result[key] >= 0 &&
        result[key] <= maximum ? result[key] : null;
    }
  }
  for (const key of [
    'reload_elapsed_ms', 'reset_elapsed_ms', 'post_reset_elapsed_ms',
  ]) {
    if (Object.hasOwn(result, key)) {
      output[key] = Number.isFinite(result[key]) && result[key] >= 0 &&
        result[key] <= 180000 ? Math.round(result[key] * 1000) / 1000 : null;
    }
  }
  for (const key of [
    'pre_reload_shape_hash', 'reload_shape_hash', 'reset_shape_hash',
    'post_reset_shape_hash', 'pre_reload_content_hash',
    'reload_content_hash',
  ]) {
    if (Object.hasOwn(result, key)) output[key] = boundedHash(result[key]);
  }
  if (Object.hasOwn(result, 'reload_shape_preserved')) {
    output.reload_shape_preserved = result.reload_shape_preserved === true;
  }
  if (Object.hasOwn(result, 'reload_content_preserved')) {
    output.reload_content_preserved = result.reload_content_preserved === true;
  }
  if (Object.hasOwn(result, 'reset_dom_empty'))
    output.reset_dom_empty = result.reset_dom_empty === true;
  if (Object.hasOwn(result, 'visible_text_pass')) {
    output.visible_text_pass = result.visible_text_pass === true;
  }
  if (Object.hasOwn(result, 'screenshot_captured')) {
    output.screenshot_captured = result.screenshot_captured === true;
  }
  for (const key of [
    'source_binding_verified', 'mail_source_binding_verified',
    'document_source_binding_verified',
  ]) {
    if (Object.hasOwn(result, key)) {
      output[key] = result[key] === true;
    }
  }
  if (Object.hasOwn(result, 'diagnostic')) {
    const diagnostic = result.diagnostic;
    output.diagnostic = boundedDiagnostic(
      diagnostic,
      {status: diagnostic && diagnostic.response_status},
      diagnostic && diagnostic.payload_citation_count === null ? [] :
        diagnostic && Number.isInteger(diagnostic.payload_citation_count) ?
          Array.from({length: diagnostic.payload_citation_count}) : [],
    );
  }
  if (Object.hasOwn(result, 'runner_diagnostic')) {
    output.runner_diagnostic = boundedRunnerDiagnostic(
      result.runner_diagnostic,
    );
  }
  process.stdout.write(JSON.stringify(output) + '\n');
}

function resolveBrowserBinary() {
  const allowed = new Set(fixedBrowserBinaryAllowlist);
  const configured = process.env.FORMOWL_CHROMIUM_BIN;
  const candidates = [configured, ...allowed].filter(candidate =>
    typeof candidate === 'string' && allowed.has(candidate));
  for (const candidate of candidates) {
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      return candidate;
    } catch (_) {
      // Continue through the fixed, non-user-controlled browser allowlist.
    }
  }
  return null;
}

function resolveScreenshotTarget(value) {
  if (value === undefined || value === '') return null;
  if (typeof value !== 'string' || !path.isAbsolute(value)) {
    throw new Error('screenshot_capture_failed');
  }
  const target = path.resolve(value);
  if (path.dirname(target) !== '/tmp') {
    throw new Error('screenshot_capture_failed');
  }
  try {
    fs.lstatSync(target);
    throw new Error('screenshot_capture_failed');
  } catch (error) {
    if (error && error.code !== 'ENOENT') {
      throw new Error('screenshot_capture_failed');
    }
  }
  return target;
}

async function captureMailScreenshot(command, target) {
  if (!target) return false;
  let created = false;
  let descriptor = null;
  try {
    const screenshot = await command('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
      captureBeyondViewport: false,
    });
    if (!screenshot || typeof screenshot.data !== 'string' ||
        screenshot.data.length === 0) {
      throw new Error('screenshot_capture_failed');
    }
    const bytes = Buffer.from(screenshot.data, 'base64');
    if (!bytes.length || bytes.toString('base64') !== screenshot.data) {
      throw new Error('screenshot_capture_failed');
    }
    const flags = fs.constants.O_WRONLY | fs.constants.O_CREAT |
      fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW || 0);
    descriptor = fs.openSync(target, flags, 0o600);
    created = true;
    if (!fs.fstatSync(descriptor).isFile()) {
      throw new Error('screenshot_capture_failed');
    }
    fs.writeFileSync(descriptor, bytes);
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = null;
    return true;
  } catch (_) {
    if (descriptor !== null) {
      try { fs.closeSync(descriptor); } catch (_) {}
    }
    if (created) {
      try { fs.unlinkSync(target); } catch (_) {}
    }
    throw new Error('screenshot_capture_failed');
  }
}

function runnerModeFromArgv(argv = process.argv) {
  return {
    basicOnly: argv.includes('--basic-only'),
    live: argv.includes('--live'),
    sourceNeutralSynthetic: argv.includes('--synthetic-source-neutral'),
  };
}

async function main() {
  const state = createRunnerState();
  lastRunnerState = state;
  let browser = null;
  let cdp = null;
  let exited = null;
  let userDir = null;
  let eventError = false;
  const {basicOnly, live, sourceNeutralSynthetic} = runnerModeFromArgv();
  const rawLiveDocumentPrompt = process.env.FORMOWL_UAT_DOCUMENT_PROMPT;
  const liveDocumentPrompt = rawLiveDocumentPrompt === undefined ?
    null : normalizeOperatorDocumentPrompt(rawLiveDocumentPrompt);
  const documentPromptInvalid = rawLiveDocumentPrompt !== undefined &&
    liveDocumentPrompt === null;
  const documentPhaseRequested = !basicOnly && !sourceNeutralSynthetic &&
    liveDocumentPrompt !== null;
  const followupsRequested =
    process.env.FORMOWL_UAT_ACCEPTANCE_FOLLOWUPS === '1' ||
    documentPhaseRequested;
  try {
    if (documentPromptInvalid) {
      recordRunnerFailure(state, 'unknown_failure', 'startup');
      safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
      return 1;
    }
    let screenshotTarget;
    try {
      screenshotTarget = resolveScreenshotTarget(
        process.env.FORMOWL_UAT_SCREENSHOT_PATH,
      );
    } catch (_) {
      recordRunnerFailure(state, 'screenshot_capture_failed', 'startup');
      safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
      return 1;
    }
    let target;
    try {
      target = new URL(process.env.FORMOWL_UAT_URL ||
        'http://127.0.0.1:8088/');
    } catch (_) {
      recordRunnerFailure(state, 'target_invalid');
      safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
      return 1;
    }
    if (!['http:', 'https:'].includes(target.protocol) ||
        target.username || target.password || target.search || target.hash) {
      recordRunnerFailure(state, 'target_invalid');
      safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
      return 1;
    }
    if (sourceNeutralSynthetic && (!live || !process.env.FORMOWL_UAT_URL ||
        !new Set(['127.0.0.1', 'localhost', '::1']).has(target.hostname))) {
      recordRunnerFailure(state, 'target_invalid');
      safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
      return 1;
    }
    const turnMs = Number(process.env.FORMOWL_UAT_TIMEOUT_MS || 90000);
    if (!Number.isInteger(turnMs) || turnMs < 1000 || turnMs > 180000) {
      recordRunnerFailure(state, 'timeout_invalid');
      safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
      return 1;
    }
    const authFile = process.env.FORMOWL_UAT_BASIC_AUTH_FILE;
    const auth = authFile ? fs.readFileSync(authFile, 'utf8').trim() : '';
    state.phase = 'browser_launch';
    const browserBinary = resolveBrowserBinary();
    if (!browserBinary) {
      recordRunnerFailure(state, 'browser_missing');
      safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
      return 1;
    }
    userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'formowl-chromium-'));
    try {
      browser = spawn(browserBinary, [
        '--headless=new', '--no-sandbox', '--disable-gpu',
        '--disable-dev-shm-usage', '--disable-background-networking',
        '--no-first-run', '--remote-debugging-pipe',
        `--user-data-dir=${userDir}`, 'about:blank',
      ], {stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe']});
    } catch (_) {
      recordRunnerFailure(state, 'spawn_error');
      safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
      return 1;
    }
    browser.stderr.on('data', data => noteBrowserStderr(state, data));
    browser.stderr.on('error', error => {
      recordRunnerFailure(state, classifyPipeFailure(error), state.phase);
    });
    browser.on('error', error => {
      recordRunnerFailure(state, 'child_error', state.phase);
    });
    browser.on('exit', (code, signal) => {
      state.browser_exit_code = code;
      state.browser_signal = typeof signal === 'string' ? signal : null;
      if (signal) recordRunnerFailure(state, 'child_signal', state.phase);
      else if (code !== 0) recordRunnerFailure(state, 'child_exit', state.phase);
    });
    exited = new Promise(resolve => {
      let settled = false;
      const finish = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      browser.once('exit', finish);
      browser.once('error', finish);
    });
    cdp = new Cdp(browser, (reason, _error, commandName) => {
      recordRunnerFailure(state, reason, state.phase, commandName);
    });
    state.phase = 'cdp_connect';
    const {browserContextId} = await cdp.command('Target.createBrowserContext', {
      disposeOnDetach: true,
    });
    state.phase = 'target_create';
    const {targetId} = await cdp.command('Target.createTarget', {
      url: 'about:blank', browserContextId,
    });
    const {sessionId} = await cdp.command('Target.attachToTarget', {
      targetId, flatten: true,
    });
    const command = (method, params) => cdp.command(method, params, sessionId);
    const evaluate = async expression => {
      const value = await command('Runtime.evaluate', {
        expression, awaitPromise: true, returnByValue: true, userGesture: true,
      });
      if (value.exceptionDetails) {
        recordRunnerFailure(state, 'page_evaluation_failed', state.phase);
        throw new Error('page_evaluation_failed');
      }
      return value.result && value.result.value;
    };
    const readTranscriptShape = () => evaluate(`(async() => {
      const articles = [...document.querySelectorAll(
        '#conversation-transcript article')];
      const assistants = articles.filter(article =>
        article.dataset.role === 'assistant');
      const turns = articles.filter(article =>
        ['user', 'assistant'].includes(article.dataset.role)).map(article => {
          const content = article.querySelector('.turn-content');
          const visible = node => node && node.getClientRects().length > 0 &&
            getComputedStyle(node).visibility !== 'hidden' &&
            getComputedStyle(node).display !== 'none';
          return {
            role: article.dataset.role,
            text: visible(content) ? content.textContent.trim() : '',
            citations: [...article.querySelectorAll('.turn-citations li')]
              .filter(visible).map(item => item.textContent.trim()),
          };
        });
      const digest = await crypto.subtle.digest(
        'SHA-256',
        new TextEncoder().encode(JSON.stringify(turns)),
      );
      const contentFingerprint = 'sha256:' + Array.from(
        new Uint8Array(digest),
        byte => byte.toString(16).padStart(2, '0'),
      ).join('');
      const safeStatus = status => [
        'pending', 'complete', 'partial', 'clarification_required', 'error',
      ].includes(status) ? status : 'unknown';
      return {
        article_count: articles.length,
        assistant_count: assistants.length,
        pending_count: articles.filter(article =>
          article.dataset.status === 'pending').length,
        assistant_statuses: assistants.map(article =>
          safeStatus(article.dataset.status)),
        assistant_citation_counts: assistants.map(article =>
          article.querySelectorAll('.turn-citations li').length),
        content_fingerprint: contentFingerprint,
      };
    })()`);
    const waitFor = async (expression, duration) => {
      const deadline = Date.now() + duration;
      while (Date.now() < deadline) {
        if (eventError) {
          recordRunnerFailure(state, 'request_control_failed', state.phase);
          throw new Error('request_control_failed');
        }
        if (await evaluate(expression)) return true;
        await sleep(200);
      }
      return false;
    };
    cdp.onEvent = event => {
      if (event.method !== 'Fetch.requestPaused') return;
      const {requestId, request} = event.params;
      const sameOrigin = new URL(request.url).origin === target.origin;
      const params = {requestId};
      if (sameOrigin && auth) {
        params.headers = Object.entries(request.headers)
          .filter(([name]) => name.toLowerCase() !== 'authorization')
          .map(([name, value]) => ({name, value}));
        params.headers.push({name: 'Authorization',
          value: `Basic ${Buffer.from(auth).toString('base64')}`});
      }
      if (!sameOrigin) params.errorReason = 'BlockedByClient';
      command(sameOrigin ? 'Fetch.continueRequest' : 'Fetch.failRequest', params)
        .catch(() => {
          if (cdp && cdp.closed) return;
          eventError = true;
          recordRunnerFailure(state, 'request_control_failed', state.phase);
        });
    };
    state.phase = 'ready_check';
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Fetch.enable', {patterns: [{urlPattern: '*'}]});
    await command('Page.addScriptToEvaluateOnNewDocument', {
      source: `(${installProbe.toString()})();`,
    });
    state.phase = 'page_navigation';
    await command('Page.navigate', {url: target.href});
    state.phase = 'auth_gate';
    if (!await waitFor(`document.querySelector('#auth-controls') !== null`, 15000)) {
      recordRunnerFailure(state, 'page_not_ready');
      safeOutput({status: 'page_not_ready', runner_diagnostic: state}, {final: true});
      return 1;
    }
    if (!await evaluate(`document.querySelector('#auth-controls').dataset.authenticated === 'true'`)) {
      recordRunnerFailure(state, 'auth_required');
      safeOutput({status: 'auth_required', runner_diagnostic: state}, {final: true});
      return 1;
    }
    state.phase = 'ready_check';
    if (!await waitFor(`window.__formowlUatProbe?.transcript?.ok &&
      !document.querySelector('#prompt-input').disabled &&
      !document.querySelector('#send-button').disabled &&
      document.querySelector('#loading-state').hidden`, 15000)) {
      recordRunnerFailure(state, 'page_not_ready');
      safeOutput({status: 'page_not_ready', runner_diagnostic: state}, {final: true});
      return 1;
    }
    if (!await evaluate(`window.__formowlUatProbe.transcript.count === 0 &&
      document.querySelectorAll('#conversation-transcript article').length === 0 &&
      window.__formowlUatProbe.chat.length === 0`)) {
      recordRunnerFailure(state, 'session_not_fresh');
      safeOutput({status: 'session_not_fresh', runner_diagnostic: state}, {final: true});
      return 1;
    }
    if (basicOnly) {
      const basicOutput = (status, result = {}) => {
        result.status = status;
        result.acceptance_surface = 'basic_only';
        result.mail_acceptance = 'not_run';
        result.ordinary_mcp_zero = result.ordinary_mcp_zero === true;
        result.runner_diagnostic = state;
        safeOutput(result, {final: true});
        return status === 'basic_only_passed' ? 0 : 1;
      };
      const submitOrdinary = async (chatIndex, prompt) => {
        const start = Date.now();
        state.phase = 'ordinary_submit';
        await evaluate(`(() => {
          const input = document.querySelector('#prompt-input');
          if (!input || input.disabled) throw new Error('not_ready');
          input.value = ${JSON.stringify(prompt)};
          input.dispatchEvent(new Event('input', {bubbles:true}));
          document.querySelector('#chat-form').requestSubmit();
        })()`);
        state.phase = 'ordinary_wait';
        const ready = await waitFor(`window.__formowlUatProbe.chat.length === ${chatIndex + 1} &&
          document.querySelectorAll('#conversation-transcript article[data-role="assistant"]').length === ${chatIndex + 1} &&
          !document.querySelector('#conversation-transcript article[data-status="pending"]') &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#send-button').disabled`, turnMs);
        if (!ready) {
          recordRunnerFailure(state, 'turn_timeout');
          return {
            status: 'basic_only_timeout',
            elapsed_ms: Date.now() - start,
            visible_text_pass: false,
          };
        }
        const result = await evaluate(`(() => {
          const assistant = [...document.querySelectorAll(
            '#conversation-transcript article[data-role="assistant"]')].at(-1);
          const content = assistant.querySelector('.turn-content');
          const error = document.querySelector('#error-text');
          return (${classify.toString()})('ordinary',
            window.__formowlUatProbe.chat[${chatIndex}], {
              status: assistant.dataset.status,
              text: content.textContent.trim(),
              visible: content.getClientRects().length > 0 &&
                getComputedStyle(content).visibility !== 'hidden',
              incomplete_visible: false,
              error: error && !error.hidden ? error.textContent.trim() : '',
              citations: assistant.querySelectorAll('.turn-citations li').length,
              citation_labels: [...assistant.querySelectorAll(
                '.turn-citations li')].map(item => item.textContent.trim()),
            });
        })()`);
        result.elapsed_ms = Date.now() - start;
        result.ordinary_mcp_zero = result.status === 'ordinary_passed' &&
          result.tool_count === 0 && result.citation_count === 0;
        return result;
      };
      try {
        const first = await submitOrdinary(0, ordinaryPrompt);
        if (first.status !== 'ordinary_passed' ||
            first.ordinary_mcp_zero !== true) {
          return basicOutput(first.status === 'basic_only_timeout' ?
            'basic_only_timeout' : 'basic_only_failed', first);
        }

        const preReloadShape = boundedTranscriptShape(
          await readTranscriptShape(),
        );
        if (!preReloadShape || preReloadShape.assistant_count !== 1 ||
            preReloadShape.pending_count !== 0) {
          throw new Error('pre_reload_snapshot_failed');
        }
        const reloadStart = Date.now();
        state.phase = 'ready_check';
        await command('Page.reload', {ignoreCache: true});
        const reloaded = await waitFor(`window.__formowlUatProbe?.transcript?.ok &&
          window.__formowlUatProbe.transcript.count === 1 &&
          document.querySelectorAll('#conversation-transcript article[data-role="assistant"]').length === 1 &&
          window.__formowlUatProbe.chat.length === 0 &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#send-button').disabled`, turnMs);
        const reloadCount = reloaded ?
          await evaluate('window.__formowlUatProbe.transcript.count') : null;
        const reloadShape = reloaded ? boundedTranscriptShape(
          await readTranscriptShape(),
        ) : null;
        const reloadChatCount = reloaded ? await evaluate(
          'window.__formowlUatProbe.chat.length',
        ) : null;
        const reloadElapsed = Date.now() - reloadStart;
        if (!reloaded || reloadCount !== 1 || reloadChatCount !== 0 ||
            !reloadShape || reloadShape.assistant_count !== 1 ||
            reloadShape.pending_count !== 0 ||
            reloadShape.shape_hash !== preReloadShape.shape_hash ||
            reloadShape.content_fingerprint !==
              preReloadShape.content_fingerprint) {
          throw new Error('reload_failed');
        }

        const resetStart = Date.now();
        state.phase = 'ready_check';
        await evaluate(`(() => { const button = document.querySelector(
          '#new-conversation-button'); if (!button || button.disabled) {
          throw new Error('reset_not_ready'); } button.click(); })()`);
        const resetDomEmpty = await waitFor(`document.querySelectorAll(
          '#conversation-transcript article').length === 0 &&
          !document.querySelector('#empty-conversation').hidden &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#new-conversation-button').disabled`, turnMs);
        const resetCount = resetDomEmpty ? await evaluate(
          `(async()=>{const r=await fetch('/api/transcript',{cache:'no-store'});
          if(!r.ok)return -1;const p=await r.json().catch(()=>null);
          return p&&Array.isArray(p.turns)?p.turns.length:-1})()`) : null;
        const resetShape = resetDomEmpty ? boundedTranscriptShape(
          await readTranscriptShape(),
        ) : null;
        const resetElapsed = Date.now() - resetStart;
        if (!resetDomEmpty || resetCount !== 0 || !resetShape ||
            resetShape.article_count !== 0 ||
            resetShape.assistant_count !== 0 ||
            resetShape.pending_count !== 0) {
          throw new Error('reset_failed');
        }

        const postResetStart = Date.now();
        const postReset = await submitOrdinary(0, ordinaryPrompt);
        const postResetShape = boundedTranscriptShape(
          await readTranscriptShape(),
        );
        const postResetCount = await evaluate(
          'window.__formowlUatProbe.transcript.count',
        );
        const postResetElapsed = Date.now() - postResetStart;
        if (postReset.status !== 'ordinary_passed' ||
            postReset.ordinary_mcp_zero !== true ||
            postResetCount !== 1 || !postResetShape ||
            postResetShape.assistant_count !== 1 ||
            postResetShape.pending_count !== 0) {
          return basicOutput(postReset.status === 'basic_only_timeout' ?
            'basic_only_timeout' : 'basic_only_failed', {
            ...postReset,
            reload_transcript_count: reloadCount,
            reset_transcript_count: resetCount,
            post_reset_transcript_count: postResetCount,
            pre_reload_visible_turn_count: preReloadShape.assistant_count,
            reload_visible_turn_count: reloadShape.assistant_count,
            reload_visible_pending_count: reloadShape.pending_count,
            reset_visible_article_count: resetShape.article_count,
            reset_visible_turn_count: resetShape.assistant_count,
            post_reset_visible_turn_count: postResetShape ?
              postResetShape.assistant_count : null,
            post_reset_visible_pending_count: postResetShape ?
              postResetShape.pending_count : null,
            pre_reload_shape_hash: preReloadShape.shape_hash,
            reload_shape_hash: reloadShape.shape_hash,
            reset_shape_hash: resetShape.shape_hash,
            post_reset_shape_hash: postResetShape ?
              postResetShape.shape_hash : null,
            pre_reload_content_hash: preReloadShape.content_fingerprint,
            reload_content_hash: reloadShape.content_fingerprint,
            reload_shape_preserved: reloadShape.shape_hash ===
              preReloadShape.shape_hash,
            reload_content_preserved: reloadShape.content_fingerprint ===
              preReloadShape.content_fingerprint,
            reload_elapsed_ms: reloadElapsed,
            reset_elapsed_ms: resetElapsed,
            post_reset_elapsed_ms: postResetElapsed,
          });
        }
        return basicOutput('basic_only_passed', {
          ...postReset,
          reload_transcript_count: reloadCount,
          reset_transcript_count: resetCount,
          post_reset_transcript_count: postResetCount,
          pre_reload_visible_turn_count: preReloadShape.assistant_count,
          reload_visible_turn_count: reloadShape.assistant_count,
          reload_visible_pending_count: reloadShape.pending_count,
          reset_visible_article_count: resetShape.article_count,
          reset_visible_turn_count: resetShape.assistant_count,
          post_reset_visible_turn_count: postResetShape.assistant_count,
          post_reset_visible_pending_count: postResetShape.pending_count,
          pre_reload_shape_hash: preReloadShape.shape_hash,
          reload_shape_hash: reloadShape.shape_hash,
          reset_shape_hash: resetShape.shape_hash,
          post_reset_shape_hash: postResetShape.shape_hash,
          pre_reload_content_hash: preReloadShape.content_fingerprint,
          reload_content_hash: reloadShape.content_fingerprint,
          reload_shape_preserved: reloadShape.shape_hash ===
            preReloadShape.shape_hash,
          reload_content_preserved: reloadShape.content_fingerprint ===
            preReloadShape.content_fingerprint,
          reload_elapsed_ms: reloadElapsed,
          reset_elapsed_ms: resetElapsed,
          post_reset_elapsed_ms: postResetElapsed,
        });
      } catch (_) {
        recordRunnerFailure(state, 'unknown_failure', state.phase);
        return basicOutput('basic_only_failed');
      }
    }
    if (sourceNeutralSynthetic) {
      const sourceNeutralOutput = (status, result = {}) => {
        result.status = status;
        result.acceptance_surface = 'source_neutral_synthetic';
        result.provider_finalization = 'not_exercised_provider_free';
        result.mail_acceptance = 'synthetic_only';
        result.document_acceptance = 'synthetic_only';
        result.runner_diagnostic = state;
        safeOutput(result, {final: true});
        return status === 'source_neutral_passed' ? 0 : 1;
      };
      const expectedEvidenceBindings = parseExpectedEvidenceBindings(
        process.env.FORMOWL_UAT_EXPECTED_EVIDENCE_BINDINGS,
      );
      if (expectedEvidenceBindings === null) {
        return sourceNeutralOutput('source_neutral_failed', {
          source_binding_verified: false,
        });
      }
      const submit = async (index, phase, prompt, sourceNeutral = false) => {
        const start = Date.now();
        state.phase = phase + '_submit';
        await evaluate(`(() => {
          const input = document.querySelector('#prompt-input');
          if (!input || input.disabled) throw new Error('not_ready');
          input.value = ${JSON.stringify(prompt)};
          input.dispatchEvent(new Event('input', {bubbles:true}));
          document.querySelector('#chat-form').requestSubmit();
        })()`);
        state.phase = phase + '_wait';
        const ready = await waitFor(`window.__formowlUatProbe.chat.length === ${index + 1} &&
          document.querySelectorAll('#conversation-transcript article[data-role="assistant"]').length === ${index + 1} &&
          !document.querySelector('#conversation-transcript article[data-status="pending"]') &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#send-button').disabled`, turnMs);
        if (!ready) {
          recordRunnerFailure(state, 'turn_timeout');
          return {status: 'source_neutral_timeout', elapsed_ms: Date.now() - start};
        }
        const expectedBinding = (phase === 'mail' || phase === 'document') ?
          expectedEvidenceBindings[phase] : null;
        const result = await evaluate(`(async () => {
          const assistant = [...document.querySelectorAll(
            '#conversation-transcript article[data-role="assistant"]')].at(-1);
          const content = assistant.querySelector('.turn-content');
          const error = document.querySelector('#error-text');
          const answerText = content.textContent.trim();
          const citationLabels = [...assistant.querySelectorAll(
            '.turn-citations li')].map(item => item.textContent.trim());
          const fingerprint = async value => {
            const digest = await crypto.subtle.digest(
              'SHA-256', new TextEncoder().encode(value));
            return 'sha256:' + Array.from(new Uint8Array(digest), byte =>
              byte.toString(16).padStart(2, '0')).join('');
          };
          return (${classify.toString()})(${JSON.stringify(phase)},
            window.__formowlUatProbe.chat[${index}], {
              status: assistant.dataset.status,
              text: answerText,
              visible: content.getClientRects().length > 0 &&
                getComputedStyle(content).visibility !== 'hidden',
              incomplete_visible: [...assistant.querySelectorAll(
                '.turn-clarification')].some(node =>
                Boolean(node.textContent.trim()) &&
                node.getClientRects().length > 0 &&
                getComputedStyle(node).visibility !== 'hidden'),
              error: error && !error.hidden ? error.textContent.trim() : '',
              citations: assistant.querySelectorAll('.turn-citations li').length,
              citation_labels: citationLabels,
              answer_fingerprint: await fingerprint(answerText),
              citation_fingerprints: await Promise.all(
                citationLabels.map(fingerprint)),
            }, {sourceNeutral: ${sourceNeutral}, expectedEvidenceBinding: ${JSON.stringify(expectedBinding)}});
        })()`);
        result.elapsed_ms = Date.now() - start;
        return result;
      };
      try {
        const ordinary = await submit(0, 'ordinary', ordinaryPrompt);
        if (ordinary.status !== 'ordinary_passed' || ordinary.tool_count !== 0 ||
            ordinary.citation_count !== 0) {
          return sourceNeutralOutput('source_neutral_failed', ordinary);
        }
        const mail = await submit(1, 'mail', syntheticMailPrompt, true);
        if (mail.status !== 'source_neutral_cited_result') {
          return sourceNeutralOutput(mail.status === 'source_neutral_timeout' ?
            'source_neutral_timeout' : 'source_neutral_failed', {
            ...ordinary, ...mail, mail_tool_count: mail.tool_count,
            mail_citation_count: mail.citation_count,
            mail_source_binding_verified: mail.source_binding_verified === true,
          });
        }
        const document = await submit(2, 'document', syntheticDocumentPrompt, true);
        if (document.status !== 'source_neutral_cited_result') {
          return sourceNeutralOutput(document.status === 'source_neutral_timeout' ?
            'source_neutral_timeout' : 'source_neutral_failed', {
            ...ordinary, ...mail, ...document,
            mail_tool_count: mail.tool_count,
            mail_citation_count: mail.citation_count,
            document_tool_count: document.tool_count,
            document_citation_count: document.citation_count,
            mail_source_binding_verified: mail.source_binding_verified === true,
            document_source_binding_verified: document.source_binding_verified === true,
          });
        }
        const preReloadShape = boundedTranscriptShape(await readTranscriptShape());
        if (!preReloadShape || preReloadShape.assistant_count !== 3 ||
            preReloadShape.pending_count !== 0) throw new Error('pre_reload_snapshot_failed');
        const reloadStart = Date.now();
        state.phase = 'ready_check';
        await command('Page.reload', {ignoreCache: true});
        const reloaded = await waitFor(`window.__formowlUatProbe?.transcript?.ok &&
          window.__formowlUatProbe.transcript.count === 3 &&
          document.querySelectorAll('#conversation-transcript article[data-role="assistant"]').length === 3 &&
          window.__formowlUatProbe.chat.length === 0 &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#send-button').disabled`, turnMs);
        const reloadCount = reloaded ?
          await evaluate('window.__formowlUatProbe.transcript.count') : null;
        const reloadShape = reloaded ? boundedTranscriptShape(
          await readTranscriptShape(),
        ) : null;
        const reloadElapsed = Date.now() - reloadStart;
        if (!reloaded || reloadCount !== 3 || !reloadShape ||
            reloadShape.assistant_count !== 3 || reloadShape.pending_count !== 0 ||
            reloadShape.shape_hash !== preReloadShape.shape_hash ||
            reloadShape.content_fingerprint !== preReloadShape.content_fingerprint) {
          throw new Error('reload_failed');
        }
        const resetStart = Date.now();
        state.phase = 'ready_check';
        await evaluate(`(() => { const button = document.querySelector(
          '#new-conversation-button'); if (!button || button.disabled) {
          throw new Error('reset_not_ready'); } button.click(); })()`);
        const resetDomEmpty = await waitFor(`document.querySelectorAll(
          '#conversation-transcript article').length === 0 &&
          !document.querySelector('#empty-conversation').hidden &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#new-conversation-button').disabled`, turnMs);
        const resetCount = resetDomEmpty ? await evaluate(
          `(async()=>{const r=await fetch('/api/transcript',{cache:'no-store'});
          if(!r.ok)return -1;const p=await r.json().catch(()=>null);
          return p&&Array.isArray(p.turns)?p.turns.length:-1})()`) : null;
        const resetShape = resetDomEmpty ? boundedTranscriptShape(
          await readTranscriptShape(),
        ) : null;
        const resetElapsed = Date.now() - resetStart;
        if (!resetDomEmpty || resetCount !== 0 || !resetShape ||
            resetShape.article_count !== 0 || resetShape.assistant_count !== 0 ||
            resetShape.pending_count !== 0) throw new Error('reset_failed');
        // The browser probe has already observed three pre-reset requests;
        // reset its client-local counter so the new server session is checked
        // from zero without weakening the server transcript assertions above.
        await evaluate('window.__formowlUatProbe.chat = []');
        const postReset = await submit(0, 'ordinary', ordinaryPrompt);
        const postResetCount = await evaluate(
          'window.__formowlUatProbe.transcript.count',
        );
        const postResetShape = boundedTranscriptShape(await readTranscriptShape());
        if (postReset.status !== 'ordinary_passed' || postReset.tool_count !== 0 ||
            postReset.citation_count !== 0 || postResetCount !== 1 ||
            !postResetShape || postResetShape.assistant_count !== 1 ||
            postResetShape.pending_count !== 0) throw new Error('reset_ordinary_failed');
        const result = {
          ...postReset,
          mail_tool_count: mail.tool_count,
          mail_citation_count: mail.citation_count,
          document_tool_count: document.tool_count,
          document_citation_count: document.citation_count,
          mail_source_binding_verified: mail.source_binding_verified === true,
          document_source_binding_verified: document.source_binding_verified === true,
          ordinary_mcp_zero: ordinary.tool_count === 0 && ordinary.citation_count === 0 &&
            postReset.tool_count === 0 && postReset.citation_count === 0,
          reload_transcript_count: reloadCount,
          reset_transcript_count: resetCount,
          post_reset_transcript_count: postResetCount,
          pre_reload_visible_turn_count: preReloadShape.assistant_count,
          reload_visible_turn_count: reloadShape.assistant_count,
          reload_visible_pending_count: reloadShape.pending_count,
          reset_visible_article_count: resetShape.article_count,
          reset_visible_turn_count: resetShape.assistant_count,
          post_reset_visible_turn_count: postResetShape.assistant_count,
          post_reset_visible_pending_count: postResetShape.pending_count,
          pre_reload_shape_hash: preReloadShape.shape_hash,
          reload_shape_hash: reloadShape.shape_hash,
          reset_shape_hash: resetShape.shape_hash,
          post_reset_shape_hash: postResetShape.shape_hash,
          pre_reload_content_hash: preReloadShape.content_fingerprint,
          reload_content_hash: reloadShape.content_fingerprint,
          reload_shape_preserved: reloadShape.shape_hash === preReloadShape.shape_hash,
          reload_content_preserved: reloadShape.content_fingerprint ===
            preReloadShape.content_fingerprint,
          reset_dom_empty: true,
          reload_elapsed_ms: reloadElapsed,
          reset_elapsed_ms: resetElapsed,
        };
        return sourceNeutralOutput('source_neutral_passed', result);
      } catch (_) {
        recordRunnerFailure(state, 'unknown_failure', state.phase);
        return sourceNeutralOutput('source_neutral_failed');
      }
    }
    let liveMailResult = null;
    let liveDocumentResult = null;
    const liveTurns = [
      [0, 'ordinary', ordinaryPrompt],
      [1, 'mail', mailPrompt],
    ];
    if (documentPhaseRequested) {
      liveTurns.push([2, 'document', liveDocumentPrompt]);
    }
    let liveDocumentBinding = null;
    if (documentPhaseRequested) {
      const expectedEvidenceBindings = parseExpectedEvidenceBindings(
        process.env.FORMOWL_UAT_EXPECTED_EVIDENCE_BINDINGS,
        ['document'],
      );
      if (expectedEvidenceBindings === null) {
        recordRunnerFailure(state, 'unknown_failure', 'startup');
        safeOutput({status: 'runner_error', runner_diagnostic: state}, {final: true});
        return 1;
      }
      liveDocumentBinding = expectedEvidenceBindings.document;
    }
    for (const [index, phase, prompt] of liveTurns) {
      const start = Date.now();
      state.phase = phase + '_submit';
      await evaluate(`(() => {
        const input = document.querySelector('#prompt-input');
        if (!input || input.disabled) throw new Error('not_ready');
        input.value = ${JSON.stringify(prompt)};
        input.dispatchEvent(new Event('input', {bubbles:true}));
        document.querySelector('#chat-form').requestSubmit();
      })()`);
      state.phase = phase + '_wait';
      const ready = await waitFor(`window.__formowlUatProbe.chat.length === ${index + 1} &&
        document.querySelectorAll('#conversation-transcript article[data-role="assistant"]').length === ${index + 1} &&
        !document.querySelector('#conversation-transcript article[data-status="pending"]') &&
        document.querySelector('#loading-state').hidden &&
        !document.querySelector('#send-button').disabled`, turnMs);
      if (!ready) {
        recordRunnerFailure(state, 'turn_timeout');
        safeOutput({status: phase + '_timeout', tool_count: null,
          citation_count: null, elapsed_ms: Date.now() - start,
          visible_text_pass: false, runner_diagnostic: state}, {final: true});
        return 1;
      }
      let screenshotCaptured = false;
      if (phase === 'mail' && screenshotTarget) {
        try {
          screenshotCaptured = await captureMailScreenshot(
            command,
            screenshotTarget,
          );
        } catch (_) {
          recordRunnerFailure(state, 'screenshot_capture_failed', state.phase);
          safeOutput({status: 'runner_error', runner_diagnostic: state},
            {final: true});
          return 1;
        }
      }
      const expectedBinding = phase === 'document' ? liveDocumentBinding : null;
      const result = await evaluate(`(async () => {
        const assistant = [...document.querySelectorAll(
          '#conversation-transcript article[data-role="assistant"]')].at(-1);
        const content = assistant.querySelector('.turn-content');
        const error = document.querySelector('#error-text');
        const answerText = content.textContent.trim();
        const citationLabels = [...assistant.querySelectorAll(
          '.turn-citations li')].map(item => item.textContent.trim());
        const fingerprint = async value => {
          const digest = await crypto.subtle.digest(
            'SHA-256', new TextEncoder().encode(value));
          return 'sha256:' + Array.from(new Uint8Array(digest), byte =>
            byte.toString(16).padStart(2, '0')).join('');
        };
        return (${classify.toString()})(${JSON.stringify(phase)},
          window.__formowlUatProbe.chat[${index}], {
            status: assistant.dataset.status,
            text: answerText,
            visible: content.getClientRects().length > 0 &&
              getComputedStyle(content).visibility !== 'hidden',
            incomplete_visible: [...assistant.querySelectorAll(
              '.turn-clarification')].some(node =>
              Boolean(node.textContent.trim()) &&
              node.getClientRects().length > 0 &&
              getComputedStyle(node).visibility !== 'hidden'),
            error: error && !error.hidden ? error.textContent.trim() : '',
            citations: citationLabels.length,
            citation_labels: citationLabels,
            answer_fingerprint: await fingerprint(answerText),
            citation_fingerprints: await Promise.all(
              citationLabels.map(fingerprint)),
          }, {expectedEvidenceBinding: ${JSON.stringify(expectedBinding)}});
      })()`);
      result.elapsed_ms = Date.now() - start;
      result.runner_diagnostic = state;
      if (screenshotCaptured) result.screenshot_captured = true;
      const passed = result.status === phase +
        (phase === 'ordinary' ? '_passed' : '_cited_result');
      safeOutput(result, {final: !passed || (phase === 'mail' && !followupsRequested)});
      if (!passed) {
        return 1; // Never continue after a failed governed turn.
      }
      if (phase === 'mail') liveMailResult = result;
      if (phase === 'document') liveDocumentResult = result;
    }
    if (followupsRequested) {
      try {
        const expectedPreReloadTurnCount = liveTurns.length;
        const preReloadShape = boundedTranscriptShape(
          await readTranscriptShape(),
        );
        if (!preReloadShape ||
            preReloadShape.assistant_count !== expectedPreReloadTurnCount ||
            preReloadShape.pending_count !== 0) {
          throw new Error('pre_reload_snapshot_failed');
        }

        const reloadStart = Date.now();
        state.phase = 'ready_check';
        await command('Page.reload', {ignoreCache: true});
        const reloaded = await waitFor(`window.__formowlUatProbe?.transcript?.ok &&
          window.__formowlUatProbe.transcript.count === ${expectedPreReloadTurnCount} &&
          document.querySelectorAll(
            '#conversation-transcript article[data-role="assistant"]').length ===
            ${expectedPreReloadTurnCount} &&
          window.__formowlUatProbe.chat.length === 0 &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#send-button').disabled`, turnMs);
        const reloadCount = reloaded ?
          await evaluate('window.__formowlUatProbe.transcript.count') : null;
        const reloadShape = reloaded ? boundedTranscriptShape(
          await readTranscriptShape(),
        ) : null;
        const reloadChatCount = reloaded ? await evaluate(
          'window.__formowlUatProbe.chat.length',
        ) : null;
        const reloadElapsed = Date.now() - reloadStart;
        if (!reloaded || reloadCount !== expectedPreReloadTurnCount ||
            reloadChatCount !== 0 || !reloadShape ||
            reloadShape.assistant_count !== expectedPreReloadTurnCount ||
            reloadShape.pending_count !== 0 ||
            reloadShape.shape_hash !== preReloadShape.shape_hash ||
            reloadShape.content_fingerprint !==
              preReloadShape.content_fingerprint) {
          throw new Error('reload_failed');
        }

        const resetStart = Date.now();
        state.phase = 'ready_check';
        await evaluate(`(() => { const button = document.querySelector(
          '#new-conversation-button'); if (!button || button.disabled) {
          throw new Error('reset_not_ready'); } button.click(); })()`);
        const resetDomEmpty = await waitFor(`document.querySelectorAll(
          '#conversation-transcript article').length === 0 &&
          !document.querySelector('#empty-conversation').hidden &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#new-conversation-button').disabled`, turnMs);
        const resetCount = resetDomEmpty ? await evaluate(
          `(async()=>{const r=await fetch('/api/transcript',{cache:'no-store'});
          if(!r.ok)return -1;const p=await r.json().catch(()=>null);
          return p&&Array.isArray(p.turns)?p.turns.length:-1})()`) : null;
        const resetShape = resetDomEmpty ? boundedTranscriptShape(
          await readTranscriptShape(),
        ) : null;
        const resetElapsed = Date.now() - resetStart;
        if (!resetDomEmpty || resetCount !== 0 || !resetShape ||
            resetShape.article_count !== 0 ||
            resetShape.assistant_count !== 0 ||
            resetShape.pending_count !== 0) {
          throw new Error('reset_failed');
        }

        const postResetStart = Date.now();
        state.phase = 'ordinary_submit';
        await evaluate(`(() => { const input = document.querySelector(
          '#prompt-input'); if (!input || input.disabled) throw new Error('not_ready');
          input.value = ${JSON.stringify(ordinaryPrompt)}; input.dispatchEvent(
          new Event('input', {bubbles:true})); document.querySelector(
          '#chat-form').requestSubmit(); })()`);
        state.phase = 'ordinary_wait';
        const ordinaryReady = await waitFor(`window.__formowlUatProbe.chat.length === 1 &&
          window.__formowlUatProbe.transcript?.count === 1 && document.querySelectorAll(
            '#conversation-transcript article[data-role="assistant"]').length === 1 &&
          !document.querySelector('#conversation-transcript article[data-status="pending"]') &&
          document.querySelector('#loading-state').hidden &&
          !document.querySelector('#send-button').disabled`, turnMs);
        if (!ordinaryReady) throw new Error('reset_ordinary_timeout');
        const postResetCount = await evaluate(
          'window.__formowlUatProbe.transcript.count',
        );
        const postResetShape = boundedTranscriptShape(
          await readTranscriptShape(),
        );
        const postResetElapsed = Date.now() - postResetStart;
        if (postResetCount !== 1 || !postResetShape ||
            postResetShape.assistant_count !== 1 ||
            postResetShape.pending_count !== 0) {
          throw new Error('reset_ordinary_state_failed');
        }
        const result = await evaluate(`(() => {
          const assistant = [...document.querySelectorAll(
            '#conversation-transcript article[data-role="assistant"]')].at(-1);
          const content = assistant.querySelector('.turn-content');
          const error = document.querySelector('#error-text');
          return (${classify.toString()})('ordinary',
            window.__formowlUatProbe.chat[0], {status: assistant.dataset.status,
            text: content.textContent.trim(), visible: content.getClientRects().length > 0 &&
              getComputedStyle(content).visibility !== 'hidden',
            error: error && !error.hidden ? error.textContent.trim() : '',
            citations: assistant.querySelectorAll('.turn-citations li').length,
            citation_labels: [...assistant.querySelectorAll(
              '.turn-citations li')].map(item => item.textContent.trim())});
        })()`);
        result.elapsed_ms = postResetElapsed;
        result.reload_transcript_count = reloadCount;
        result.reset_transcript_count = resetCount;
        result.post_reset_transcript_count = postResetCount;
        if (liveMailResult) {
          result.mail_tool_count = liveMailResult.tool_count;
          result.mail_citation_count = liveMailResult.citation_count;
        }
        if (liveDocumentResult) {
          result.document_tool_count = liveDocumentResult.tool_count;
          result.document_citation_count = liveDocumentResult.citation_count;
          result.document_source_binding_verified =
            liveDocumentResult.source_binding_verified === true;
        }
        result.pre_reload_visible_turn_count = preReloadShape.assistant_count;
        result.reload_visible_turn_count = reloadShape.assistant_count;
        result.reload_visible_pending_count = reloadShape.pending_count;
        result.reset_visible_article_count = resetShape.article_count;
        result.reset_visible_turn_count = resetShape.assistant_count;
        result.post_reset_visible_turn_count = postResetShape.assistant_count;
        result.post_reset_visible_pending_count = postResetShape.pending_count;
        result.pre_reload_shape_hash = preReloadShape.shape_hash;
        result.reload_shape_hash = reloadShape.shape_hash;
        result.reset_shape_hash = resetShape.shape_hash;
        result.post_reset_shape_hash = postResetShape.shape_hash;
        result.pre_reload_content_hash = preReloadShape.content_fingerprint;
        result.reload_content_hash = reloadShape.content_fingerprint;
        result.reload_shape_preserved =
          reloadShape.shape_hash === preReloadShape.shape_hash;
        result.reload_content_preserved =
          reloadShape.content_fingerprint === preReloadShape.content_fingerprint;
        result.reload_elapsed_ms = reloadElapsed;
        result.reset_elapsed_ms = resetElapsed;
        result.post_reset_elapsed_ms = postResetElapsed;
        result.reset_dom_empty = resetDomEmpty;
        result.runner_diagnostic = state;
        const documentAcceptancePassed = !documentPhaseRequested ||
          (liveDocumentResult &&
            liveDocumentResult.status === 'document_cited_result' &&
            liveDocumentResult.source_binding_verified === true);
        const passed = result.status === 'ordinary_passed' &&
          result.tool_count === 0 && result.reload_shape_preserved === true &&
          result.reload_content_preserved === true &&
          result.reset_dom_empty === true && result.reset_transcript_count === 0 &&
          result.post_reset_transcript_count === 1 &&
          documentAcceptancePassed;
        result.status = passed ? 'acceptance_followups_passed' :
          'acceptance_followups_failed';
        safeOutput(result, {final: true});
        if (!passed) return 1;
      } catch (_) {
        recordRunnerFailure(state, 'unknown_failure', state.phase);
        safeOutput({status: 'acceptance_followups_failed',
          runner_diagnostic: state}, {final: true});
        return 1;
      }
    }
    return 0;
  } finally {
    state.phase = 'cleanup';
    if (cdp) cdp.close();
    if (browser) {
      try { browser.kill('SIGTERM'); } catch (_) {}
      if (exited) await Promise.race([exited, sleep(2000)]);
      if (browser.exitCode === null) {
        try { browser.kill('SIGKILL'); } catch (_) {}
      }
      if (exited) await Promise.race([exited, sleep(1000)]);
    }
    if (userDir) fs.rmSync(userDir, {recursive: true, force: true});
  }
}

async function selfCheck() {
  const assert = require('assert/strict');
  const {EventEmitter} = require('events');
  const {PassThrough} = require('stream');
  const vm = require('vm');
  assert.equal(runnerModeFromArgv(['node', 'runner']).basicOnly, false);
  assert.equal(
    runnerModeFromArgv(['node', 'runner', '--basic-only']).basicOnly,
    true,
  );
  assert.equal(
    fixedBrowserBinaryAllowlist.includes(
      '/ms-playwright/chromium-1187/chrome-linux/chrome',
    ),
    true,
  );
  assert.equal(
    fixedBrowserBinaryAllowlist.every(candidate =>
      candidate.startsWith('/') && !candidate.includes('\0')),
    true,
  );
  assert.equal(resolveScreenshotTarget(undefined), null);
  assert.throws(
    () => resolveScreenshotTarget('relative-screenshot.png'),
    /screenshot_capture_failed/,
  );
  assert.throws(
    () => resolveScreenshotTarget('/etc/formowl-screenshot.png'),
    /screenshot_capture_failed/,
  );
  assert.throws(
    () => resolveScreenshotTarget('/tmp/nested/formowl-screenshot.png'),
    /screenshot_capture_failed/,
  );
  const screenshotPath = path.join(
    '/tmp',
    `formowl-self-check-${crypto.randomBytes(8).toString('hex')}.png`,
  );
  const screenshotBytes = Buffer.from('synthetic local screenshot bytes');
  const screenshotCalls = [];
  try {
    const screenshotTarget = resolveScreenshotTarget(screenshotPath);
    assert.equal(
      await captureMailScreenshot(async (method, params) => {
        screenshotCalls.push({method, params});
        return {data: screenshotBytes.toString('base64')};
      }, screenshotTarget),
      true,
    );
    assert.deepEqual(screenshotCalls, [{
      method: 'Page.captureScreenshot',
      params: {
        format: 'png',
        fromSurface: true,
        captureBeyondViewport: false,
      },
    }]);
    assert.deepEqual(fs.readFileSync(screenshotPath), screenshotBytes);
    assert.equal(fs.statSync(screenshotPath).mode & 0o777, 0o600);
    assert.throws(
      () => resolveScreenshotTarget(screenshotPath),
      /screenshot_capture_failed/,
    );
  } finally {
    try { fs.unlinkSync(screenshotPath); } catch (_) {}
  }
  const child = new EventEmitter();
  child.stdio = [null, null, null, new PassThrough(), new PassThrough()];
  const cdp = new Cdp(child);
  const first = cdp.command('first');
  const second = cdp.command('second');
  child.stdio[4].write(Buffer.from('{"id":2,"result":{"ok":true}}\0{"id":1,'));
  child.stdio[4].write(Buffer.from('"result":{"ok":true}}\0'));
  assert.deepEqual(await second, {ok: true});
  assert.deepEqual(await first, {ok: true});
  cdp.close();
  let closedFailure = false;
  const closedCdp = new Cdp(child, () => { closedFailure = true; });
  closedCdp.close();
  child.stdio[4].emit('error', {code: 'ECONNRESET'});
  assert.equal(closedFailure, false);
  assert.equal(CDP_COMMAND_TIMEOUT_MS, 90000);
  const slowChild = new EventEmitter();
  slowChild.stdio = [
    null, null, null, new PassThrough(), new PassThrough(),
  ];
  let slowFailure = null;
  const slowCdp = new Cdp(
    slowChild,
    (reason, _error, commandName) => {
      slowFailure = {reason, commandName};
    },
    10,
  );
  await assert.rejects(
    slowCdp.command('Target.createBrowserContext'),
    /cdp_timeout/,
  );
  assert.deepEqual(slowFailure, {
    reason: 'cdp_timeout',
    commandName: 'Target.createBrowserContext',
  });
  slowCdp.close();
  const transcriptShape = boundedTranscriptShape({
    article_count: 4,
    assistant_count: 2,
    pending_count: 0,
    assistant_statuses: ['complete', 'partial'],
    assistant_citation_counts: [0, 3],
    content_fingerprint: `sha256:${'f'.repeat(64)}`,
  });
  assert.ok(transcriptShape);
  assert.match(transcriptShape.shape_hash, /^sha256:[0-9a-f]{64}$/);
  const sameCountShapeA = boundedTranscriptShape({
    article_count: 4,
    assistant_count: 2,
    pending_count: 0,
    assistant_statuses: ['complete', 'partial'],
    assistant_citation_counts: [0, 1],
    content_fingerprint: `sha256:${crypto.createHash('sha256')
      .update(JSON.stringify([
        {role: 'user', text: 'same user', citations: []},
        {role: 'assistant', text: 'answer-a', citations: ['citation-a']},
      ]), 'utf8').digest('hex')}`,
  });
  const sameCountShapeB = boundedTranscriptShape({
    article_count: 4,
    assistant_count: 2,
    pending_count: 0,
    assistant_statuses: ['complete', 'partial'],
    assistant_citation_counts: [0, 1],
    content_fingerprint: `sha256:${crypto.createHash('sha256')
      .update(JSON.stringify([
        {role: 'user', text: 'same user', citations: []},
        {role: 'assistant', text: 'answer-b', citations: ['citation-b']},
      ]), 'utf8').digest('hex')}`,
  });
  assert.equal(sameCountShapeA.shape_hash, sameCountShapeB.shape_hash);
  assert.notEqual(
    sameCountShapeA.content_fingerprint,
    sameCountShapeB.content_fingerprint,
  );
  assert.equal(
    sameCountShapeA.shape_hash === sameCountShapeB.shape_hash &&
      sameCountShapeA.content_fingerprint ===
        sameCountShapeB.content_fingerprint,
    false,
  );
  assert.equal(
    boundedTranscriptShape({
      article_count: 1,
      assistant_count: 1,
      pending_count: 0,
      assistant_statuses: ['private'],
      assistant_citation_counts: [0],
      content_fingerprint: `sha256:${'f'.repeat(64)}`,
    }),
    null,
  );
  assert.equal(boundedMcpStatus('mcp_failed'), 'error');
  assert.equal(boundedMcpStatus('private-status'), null);
  const turn = {status: 'complete', text: '你好，今天很好！', visible: true,
    error: '', citations: 0, citation_labels: []};
  const record = {http: 200, elapsed: 1, payload: {status: 'complete',
    answer: turn.text, citations: [], diagnostic: {
      reason_code: 'provider_finalization_failed',
      phase: 'finalization',
      stop_reason: 'provider_incomplete',
      provider_error_param: 'text.format',
      provider_error_message_class: 'capacity_unavailable',
      response_body_shape: 'empty',
      provider_phase_timings: [{phase: 'finalization', elapsed_ms: 12.345}],
      mcp: {
        call_count: 0, elapsed_ms: 4.5, status: [], timeout: false,
        failure_reason: null, exception_class: 'ValueError',
        request_shape: {
          request_contract_present: false,
          table_query_present: false,
          exact_field_present: false,
          exact_inventory_kind_present: false,
          page_size_present: false,
          cursor_present: false,
        },
      },
    }}};
  // The browser evaluates only classify.toString() in a fresh global scope.
  // This must remain independent of Node-only helpers and provider state.
  const browserClassify = vm.runInNewContext(`(${classify.toString()})`, {});
  const browserOrdinaryResult = browserClassify('ordinary', record, turn);
  assert.equal(browserOrdinaryResult.status, 'ordinary_passed');
  assert.equal(
    JSON.stringify(browserOrdinaryResult.diagnostic.mcp.request_shape),
    JSON.stringify({
      request_contract_present: false,
      table_query_present: false,
      exact_field_present: false,
      exact_inventory_kind_present: false,
      page_size_present: false,
      cursor_present: false,
    }),
  );
  const ordinaryResult = classify('ordinary', record, turn);
  assert.equal(ordinaryResult.status, 'ordinary_passed');
  assert.deepEqual(ordinaryResult.diagnostic, {
    response_status: 'complete',
    reason_code: 'provider_finalization_failed',
    phase: 'finalization',
    stop_reason: 'provider_incomplete',
    provider_phase_timings: [{phase: 'finalization', elapsed_ms: 12.345}],
    mcp: {
      call_count: 0, elapsed_ms: 4.5, status: [], timeout: false,
      failure_reason: null, exception_class: 'ValueError',
      request_shape: {
        request_contract_present: false,
        table_query_present: false,
        exact_field_present: false,
        exact_inventory_kind_present: false,
        page_size_present: false,
        cursor_present: false,
      },
    },
    provider_error_param: 'text.format',
    provider_error_message_class: 'capacity_unavailable',
    response_body_shape: 'empty',
    payload_citation_count: 0,
  });
  record.payload.diagnostic.mcp.exception_class = null;
  record.payload.diagnostic.mcp.call_count = 1;
  record.payload.diagnostic.mcp.status = ['ok'];
  assert.equal(classify('ordinary', record, turn).status, 'ordinary_failed');
  assert.equal(classify('mail', record, turn).status, 'mail_unsafe_failure');
  turn.text = record.payload.answer = '測試引用回答';
  turn.citations = 1;
  const governedCitation = `mailcitation_${'a'.repeat(24)}`;
  turn.citation_labels = [governedCitation];
  turn.answer_fingerprint = textFingerprint(turn.text);
  turn.citation_fingerprints = [textFingerprint(governedCitation)];
  record.payload.citations = [governedCitation];
  record.payload.diagnostic.reason_code = null;
  record.payload.diagnostic.stop_reason = null;
  const finalizationRecord = (validationResult, citationCount = 1) => ({
    final_model: {
      citation_count: citationCount,
      citation_fingerprint: `sha256:${'d'.repeat(64)}`,
    },
    available_governed: {
      citation_count: 1,
      citation_fingerprint: `sha256:${'e'.repeat(64)}`,
    },
    validation_result: validationResult,
    repair_attempted: false,
  });
  record.payload.diagnostic.finalization_validation = [
    finalizationRecord('passed'),
  ];
  assert.equal(classify('mail', record, turn).status, 'mail_cited_result');
  const missingFinalizationRecord = JSON.parse(JSON.stringify(record));
  delete missingFinalizationRecord.payload.diagnostic.finalization_validation;
  assert.equal(
    classify('mail', missingFinalizationRecord, turn).status,
    'mail_failed',
  );
  for (const result of [
    'citation_rejected', 'coverage_rejected', 'parse_rejected',
    'provider_incomplete',
  ]) {
    const rejectedFinalizationRecord = JSON.parse(JSON.stringify(record));
    rejectedFinalizationRecord.payload.diagnostic.finalization_validation = [
      finalizationRecord(result),
    ];
    assert.equal(
      classify('mail', rejectedFinalizationRecord, turn).status,
      'mail_failed',
    );
  }
  const malformedFinalizationTail = JSON.parse(JSON.stringify(record));
  malformedFinalizationTail.payload.diagnostic.finalization_validation = [
    finalizationRecord('passed'),
    {...finalizationRecord('passed'), repair_attempted: 'invalid'},
  ];
  assert.equal(
    classify('mail', malformedFinalizationTail, turn).status,
    'mail_failed',
  );
  assert.deepEqual(
    classify('mail', malformedFinalizationTail, turn)
      .diagnostic.finalization_validation,
    [],
  );
  const oversizedFinalizationList = JSON.parse(JSON.stringify(record));
  oversizedFinalizationList.payload.diagnostic.finalization_validation = [
    finalizationRecord('passed'),
    finalizationRecord('passed'),
    finalizationRecord('passed'),
  ];
  assert.equal(
    classify('mail', oversizedFinalizationList, turn).status,
    'mail_failed',
  );
  const noFinalCitationsRecord = JSON.parse(JSON.stringify(record));
  noFinalCitationsRecord.payload.diagnostic.finalization_validation = [
    finalizationRecord('passed', 0),
  ];
  assert.equal(
    classify('mail', noFinalCitationsRecord, turn).status,
    'mail_failed',
  );
  const completedAttempt = (
    attempt,
    outcome,
    responseStatus,
    {elapsedMs = 3.5, noTools = false} = {},
  ) => ({
    attempt,
    elapsed_ms: elapsedMs,
    outcome,
    response_status: responseStatus,
    function_call_count: noTools ? 0 : 1,
    tool_choice: {
      tool_choice: noTools ? 'none' : 'required_function',
      selected_tool: noTools ? 'none' : 'query_mail_evidence',
      offered_tool_count: noTools ? 0 : 1,
      offered_tool_fingerprint: `sha256:${'a'.repeat(64)}`,
    },
  });
  const incompleteLatestAttemptRecord = JSON.parse(JSON.stringify(record));
  incompleteLatestAttemptRecord.payload.diagnostic.provider_attempt_count = 2;
  incompleteLatestAttemptRecord.payload.diagnostic.provider_attempts = [
    completedAttempt(1, 'completed', 'completed'),
    completedAttempt(2, 'incomplete', 'incomplete'),
  ];
  assert.equal(
    classify('mail', incompleteLatestAttemptRecord, turn).status,
    'mail_failed',
  );
  const malformedProviderTail = JSON.parse(JSON.stringify(record));
  malformedProviderTail.payload.diagnostic.provider_attempt_count = 2;
  malformedProviderTail.payload.diagnostic.provider_attempts = [
    completedAttempt(1, 'completed', 'completed'),
    {
      ...completedAttempt(2, 'completed', 'completed'),
      tool_choice: {...completedAttempt(2, 'completed', 'completed').tool_choice,
        offered_tool_fingerprint: 'invalid'},
    },
  ];
  assert.equal(
    classify('mail', malformedProviderTail, turn).status,
    'mail_failed',
  );
  const missingProviderAttemptCount = JSON.parse(JSON.stringify(record));
  delete missingProviderAttemptCount.payload.diagnostic.provider_attempt_count;
  missingProviderAttemptCount.payload.diagnostic.provider_attempts = [
    completedAttempt(1, 'completed', 'completed'),
  ];
  assert.equal(
    classify('mail', missingProviderAttemptCount, turn).status,
    'mail_failed',
  );
  const oversizedProviderList = JSON.parse(JSON.stringify(record));
  oversizedProviderList.payload.diagnostic.provider_attempt_count = 4;
  oversizedProviderList.payload.diagnostic.provider_attempts = [
    completedAttempt(1, 'completed', 'completed'),
    completedAttempt(2, 'completed', 'completed'),
    completedAttempt(3, 'completed', 'completed'),
    completedAttempt(3, 'completed', 'completed'),
  ];
  assert.equal(
    classify('mail', oversizedProviderList, turn).status,
    'mail_failed',
  );
  const completedProviderRecord = JSON.parse(JSON.stringify(record));
  completedProviderRecord.payload.diagnostic.provider_attempt_count = 1;
  completedProviderRecord.payload.diagnostic.provider_attempts = [
    completedAttempt(1, 'completed', 'completed'),
  ];
  assert.equal(
    classify('mail', completedProviderRecord, turn).status,
    'mail_cited_result',
  );
  const fourthRepairRecord = JSON.parse(JSON.stringify(record));
  fourthRepairRecord.payload.diagnostic.provider_attempt_count = 4;
  fourthRepairRecord.payload.diagnostic.provider_attempts = [
    completedAttempt(2, 'completed', 'completed'),
    completedAttempt(3, 'completed', 'completed', {noTools: true}),
    completedAttempt(4, 'completed', 'completed', {
      elapsedMs: 68_703,
      noTools: true,
    }),
  ];
  fourthRepairRecord.payload.diagnostic.finalization_validation = [
    finalizationRecord('citation_rejected'),
    {...finalizationRecord('passed'), repair_attempted: true},
  ];
  assert.equal(
    classify('mail', fourthRepairRecord, turn).status,
    'mail_cited_result',
  );
  const expectedMailBinding = {
    source_family: 'mail',
    answer_fingerprint: textFingerprint(turn.text),
    citation_fingerprints: [textFingerprint(governedCitation)],
  };
  const documentCitation = `sha256:${'c'.repeat(64)}`;
  const documentAnswer = '文件指出需取得書面核准。';
  const documentRecord = JSON.parse(JSON.stringify(completedProviderRecord));
  documentRecord.payload.answer = documentAnswer;
  documentRecord.payload.citations = [documentCitation];
  documentRecord.payload.diagnostic.provider_attempts[0].tool_choice.selected_tool =
    'query_effective_graph_view';
  const documentTurn = {
    status: 'complete',
    text: documentAnswer,
    visible: true,
    error: '',
    citations: 1,
    citation_labels: [documentCitation],
    answer_fingerprint: textFingerprint(documentAnswer),
    citation_fingerprints: [textFingerprint(documentCitation)],
  };
  const expectedDocumentBinding = {
    source_family: 'document_text',
    answer_fingerprint: textFingerprint(documentAnswer),
    citation_fingerprints: [textFingerprint(documentCitation)],
  };
  assert.deepEqual(
    parseExpectedEvidenceBindings(
      JSON.stringify({document: expectedDocumentBinding}),
      ['document'],
    ),
    {document: expectedDocumentBinding},
  );
  assert.equal(
    parseExpectedEvidenceBindings(
      JSON.stringify({document: expectedDocumentBinding}),
    ),
    null,
  );
  assert.equal(
    classify('document', documentRecord, documentTurn, {
      expectedEvidenceBinding: expectedDocumentBinding,
    }).status,
    'document_cited_result',
  );
  assert.equal(
    browserClassify('document', documentRecord, documentTurn, {
      expectedEvidenceBinding: expectedDocumentBinding,
    }).status,
    'document_cited_result',
  );
  const missingDocumentBinding = JSON.parse(JSON.stringify(documentRecord));
  delete missingDocumentBinding.payload.diagnostic.finalization_validation;
  assert.equal(
    classify('document', missingDocumentBinding, documentTurn, {
      expectedEvidenceBinding: expectedDocumentBinding,
    }).status,
    'document_failed',
  );
  assert.equal(
    classify('document', documentRecord, documentTurn).status,
    'document_failed',
  );
  const providerFreeSourceNeutralRecord = JSON.parse(JSON.stringify(record));
  delete providerFreeSourceNeutralRecord.payload.diagnostic.finalization_validation;
  assert.equal(
    classify('mail', providerFreeSourceNeutralRecord, turn, {
      sourceNeutral: true,
      expectedEvidenceBinding: expectedMailBinding,
    }).status,
    'source_neutral_cited_result',
  );
  assert.equal(
    browserClassify('mail', providerFreeSourceNeutralRecord, turn, {
      sourceNeutral: true,
      expectedEvidenceBinding: expectedMailBinding,
    }).status,
    'source_neutral_cited_result',
  );
  assert.equal(
    Object.hasOwn(
      classify('mail', providerFreeSourceNeutralRecord, turn, {
        sourceNeutral: true,
        expectedEvidenceBinding: expectedMailBinding,
      }).diagnostic,
      'finalization_validation',
    ),
    false,
  );
  assert.equal(
    classify('mail', providerFreeSourceNeutralRecord, turn, {
      sourceNeutral: true,
    }).status,
    'mail_failed',
  );
  const unrelatedCitation = `mailcitation_${'b'.repeat(24)}`;
  const unrelatedRecord = JSON.parse(JSON.stringify(providerFreeSourceNeutralRecord));
  unrelatedRecord.payload.answer = '不相關回答';
  unrelatedRecord.payload.citations = [unrelatedCitation];
  const unrelatedTurn = {
    ...turn,
    text: '不相關回答',
    citation_labels: [unrelatedCitation],
    answer_fingerprint: textFingerprint('不相關回答'),
    citation_fingerprints: [textFingerprint(unrelatedCitation)],
  };
  const unrelatedResult = classify('mail', unrelatedRecord, unrelatedTurn, {
    sourceNeutral: true,
    expectedEvidenceBinding: expectedMailBinding,
  });
  assert.equal(unrelatedResult.status, 'mail_failed');
  assert.equal(unrelatedResult.source_binding_verified, false);
  const partialRecord = JSON.parse(JSON.stringify(record)); partialRecord.payload.status = 'partial';
  const partialTurn = {...turn, status: 'partial', incomplete_visible: true}; assert.equal(
    classify('mail', partialRecord, partialTurn).status, 'mail_cited_result');
  partialRecord.payload.answer = '已完成整理目前可驗證資料；來源涵蓋不完整，以下為已驗證部分。';
  partialTurn.text = partialRecord.payload.answer;
  assert.equal(
    classify('mail', partialRecord, partialTurn).status,
    'mail_cited_result',
  );
  assert.equal(
    browserClassify('mail', partialRecord, partialTurn).status,
    'mail_cited_result',
  );
  const businessWorkInProgressRecord = JSON.parse(JSON.stringify(record));
  businessWorkInProgressRecord.payload.answer =
    '維修尚未完成，目前依來源紀錄持續追蹤。';
  const businessWorkInProgressTurn = {
    ...turn,
    text: businessWorkInProgressRecord.payload.answer,
  };
  assert.equal(
    classify('mail', businessWorkInProgressRecord, businessWorkInProgressTurn)
      .status,
    'mail_cited_result',
  );
  partialRecord.payload.diagnostic.reason_code = 'provider_finalization_failed';
  partialRecord.payload.diagnostic.stop_reason = 'provider_incomplete';
  partialRecord.payload.diagnostic.finalization_validation = [
    finalizationRecord('provider_incomplete'),
  ];
  partialRecord.payload.answer = '查詢失敗，請稍後再試。';
  partialTurn.text = partialRecord.payload.answer;
  assert.equal(
    classify('mail', partialRecord, partialTurn).status,
    'mail_unsafe_failure',
  );
  const degradedPartialRecord = JSON.parse(JSON.stringify(partialRecord));
  delete degradedPartialRecord.payload.diagnostic.finalization_validation;
  degradedPartialRecord.payload.answer =
    '模型最終答案未完成；目前只保留已驗證的部分資料。';
  const degradedPartialTurn = {
    ...partialTurn,
    text: degradedPartialRecord.payload.answer,
    incomplete_visible: true,
  };
  assert.equal(
    classify('mail', degradedPartialRecord, degradedPartialTurn).status,
    'mail_unsafe_failure',
  );
  degradedPartialRecord.payload.diagnostic.finalization_validation = [
    finalizationRecord('provider_incomplete'),
  ];
  assert.equal(
    classify('mail', degradedPartialRecord, degradedPartialTurn).status,
    'mail_unsafe_failure',
  );
  partialTurn.incomplete_visible = false; assert.equal(
    classify('mail', partialRecord, partialTurn).status, 'mail_unsafe_failure');
  record.payload.citations = ['synthetic-citation'];
  turn.citation_labels = ['synthetic-citation'];
  assert.equal(classify('mail', record, turn).status, 'mail_failed');
  record.payload.citations = [governedCitation];
  turn.citation_labels = [governedCitation];
  const privateMarker = 'private-diagnostic-must-not-escape';
  Object.assign(record.payload.diagnostic, {
    provider_attempt_count: 1,
    provider_attempts: [{
      attempt: 1,
      phase: 'provider_request',
      elapsed_ms: 3.5,
      outcome: 'completed',
      response_status: 'completed',
      function_call_count: 1,
      tool_choice: {
        tool_choice: 'required_function',
        selected_tool: 'query_mail_evidence',
        offered_tool_count: 1,
        offered_tool_fingerprint: `sha256:${'a'.repeat(64)}`,
      },
      provider_body: privateMarker,
      prompt: privateMarker,
      mail_message_id: privateMarker,
      raw_path: `/private/${privateMarker}`,
    }],
    mcp_citation_stages: [{
      call_index: 1,
      elapsed_ms: 4,
      raw_governed: {
        citation_count: 2,
        citation_fingerprint: `sha256:${'b'.repeat(64)}`,
      },
      compacted_presented: {
        citation_count: 1,
        citation_fingerprint: `sha256:${'c'.repeat(64)}`,
      },
      projection_result: 'reduced',
      provider_body: privateMarker,
    }],
    finalization_validation: [{
      ...finalizationRecord('passed'),
    }, {
      final_model: {
        citation_count: 0,
        citation_fingerprint: `sha256:${'d'.repeat(64)}`,
      },
      available_governed: {
        citation_count: 2,
        citation_fingerprint: `sha256:${'e'.repeat(64)}`,
      },
      validation_result: 'citation_rejected',
      repair_attempted: true,
      raw_path: `/private/${privateMarker}`,
    }],
  });
  const loopResult = classify('mail', record, turn);
  assert.equal(loopResult.status, 'mail_failed');
  assert.equal(loopResult.diagnostic.provider_attempts.length, 1);
  assert.equal(loopResult.diagnostic.mcp_citation_stages[0]
    .raw_governed.citation_count, 2);
  assert.equal(loopResult.diagnostic.finalization_validation[1]
    .validation_result, 'citation_rejected');
  const malformed = JSON.parse(JSON.stringify(record));
  malformed.payload.diagnostic.provider_attempts = [{
    attempt: 4,
    elapsed_ms: 60001,
    outcome: 'not_allowlisted',
    response_status: 'completed',
    function_call_count: 99,
    tool_choice: {
      tool_choice: 'other',
      selected_tool: 'other',
      offered_tool_count: 2,
      offered_tool_fingerprint: 'not-a-hash',
    },
  }];
  malformed.payload.diagnostic.mcp_citation_stages = [{
    call_index: 4,
    elapsed_ms: -1,
    raw_governed: {citation_count: 101, citation_fingerprint: 'bad'},
    compacted_presented: {citation_count: 0, citation_fingerprint: 'bad'},
    projection_result: 'not_allowlisted',
  }];
  malformed.payload.diagnostic.finalization_validation = [{
    final_model: {citation_count: 0, citation_fingerprint: 'bad'},
    available_governed: {citation_count: 0, citation_fingerprint: 'bad'},
    validation_result: 'not_allowlisted',
    repair_attempted: 'yes',
  }];
  const malformedResult = classify('mail', malformed, turn);
  assert.deepEqual(malformedResult.diagnostic.provider_attempts, []);
  assert.equal(Object.hasOwn(malformedResult.diagnostic, 'mcp_citation_stages'), false);
  assert.deepEqual(malformedResult.diagnostic.finalization_validation, []);
  const originalWrite = process.stdout.write;
  let captured = '';
  process.stdout.write = chunk => { captured += chunk; return true; };
  try {
    safeOutput(loopResult);
  } finally {
    process.stdout.write = originalWrite;
  }
  assert.equal(captured.includes(privateMarker), false);
  assert.equal(captured.includes('/private/'), false);
  const safeLoopOutput = JSON.parse(captured);
  assert.equal(safeLoopOutput.diagnostic.provider_attempts.length, 1);
  assert.equal(safeLoopOutput.diagnostic.mcp_citation_stages.length, 1);
  assert.equal(safeLoopOutput.diagnostic.finalization_validation.length, 2);
  const mcpFailureRecord = JSON.parse(JSON.stringify(record));
  mcpFailureRecord.http = 200;
  mcpFailureRecord.payload.status = 'error';
  mcpFailureRecord.payload.answer = '查詢失敗，請稍後再試。';
  mcpFailureRecord.payload.citations = [];
  mcpFailureRecord.payload.diagnostic.mcp = {
    call_count: 1,
    elapsed_ms: 12,
    status: ['mcp_failed'],
    timeout: false,
    failure_reason: null,
    exception_class: 'ConnectionError',
    request_discriminator: {
      tool_name: 'query_mail_evidence',
      selector_kind: 'mail_import_session_id',
      selector_present: true,
      selector_count: 1,
      selector_hash: `sha256:${'a'.repeat(64)}`,
      limit: 8,
    },
    response_stage: 'jsonrpc_error',
    query_text: privateMarker,
    selector_value: privateMarker,
    exception: privateMarker,
    request_shape: {
      request_contract_present: false,
      table_query_present: false,
      exact_field_present: false,
      exact_inventory_kind_present: false,
      page_size_present: false,
      cursor_present: false,
    },
  };
  const mcpFailureResult = classify('mail', mcpFailureRecord, {
    status: 'error',
    text: '查詢失敗，請稍後再試。',
    visible: true,
    error: '',
    citations: 0,
  });
  assert.equal(mcpFailureResult.status, 'mail_operational_failure');
  assert.equal(mcpFailureResult.diagnostic.mcp.exception_class, 'ConnectionError');
  assert.equal(
    mcpFailureResult.diagnostic.mcp.response_stage,
    'jsonrpc_error',
  );
  assert.deepEqual(
    mcpFailureResult.diagnostic.mcp.request_discriminator,
    {
      tool_name: 'query_mail_evidence',
      selector_kind: 'mail_import_session_id',
      selector_present: true,
      selector_count: 1,
      selector_hash: `sha256:${'a'.repeat(64)}`,
      limit: 8,
    },
  );
  assert.deepEqual(mcpFailureResult.diagnostic.mcp.request_shape, {
    request_contract_present: false,
    table_query_present: false,
    exact_field_present: false,
    exact_inventory_kind_present: false,
    page_size_present: false,
    cursor_present: false,
  });
  const boundedMcpFailure = boundedDiagnostic(
    mcpFailureResult.diagnostic,
    mcpFailureRecord.payload,
    [],
  );
  assert.equal(boundedMcpFailure.mcp.exception_class, 'ConnectionError');
  assert.equal(boundedMcpFailure.mcp.response_stage, 'jsonrpc_error');
  assert.deepEqual(
    boundedMcpFailure.mcp.request_discriminator,
    mcpFailureResult.diagnostic.mcp.request_discriminator,
  );
  assert.deepEqual(boundedMcpFailure.mcp.request_shape, {
    request_contract_present: false,
    table_query_present: false,
    exact_field_present: false,
    exact_inventory_kind_present: false,
    page_size_present: false,
    cursor_present: false,
  });
  const boundedMcpText = JSON.stringify(boundedMcpFailure);
  assert.equal(boundedMcpText.includes(privateMarker), false);
  const unsafeStatusRecord = JSON.parse(JSON.stringify(mcpFailureRecord));
  unsafeStatusRecord.payload.diagnostic.mcp.status = [privateMarker];
  const unsafeStatusOutput = boundedDiagnostic(
    unsafeStatusRecord.payload.diagnostic,
    unsafeStatusRecord.payload,
    [],
  );
  assert.equal(unsafeStatusOutput.mcp, null);

  // Canonical empty/pending/denied/replan results remain diagnostic evidence,
  // never successful MCP calls, even if the UI contains a governed citation.
  for (const mailStatus of [
    'not_found', 'pending_review', 'permission_denied', 'replan_required',
  ]) {
    assert.equal(boundedMcpStatus(mailStatus), mailStatus);
    for (const cited of [false, true]) {
      const mailRecord = {
        http: 200,
        payload: {
          status: 'partial',
          answer: '測試引用回答',
          citations: cited ? [governedCitation] : [],
          diagnostic: {
            mcp: {
              call_count: 2,
              elapsed_ms: 12,
              status: ['ok', mailStatus],
              timeout: false,
              failure_reason: null,
              exception_class: null,
              query_text: privateMarker,
            },
          },
        },
      };
      const mailTurn = {
        status: 'partial',
        text: mailRecord.payload.answer,
        visible: true,
        incomplete_visible: true,
        error: '',
        citations: cited ? 1 : 0,
        citation_labels: mailRecord.payload.citations,
      };
      const bounded = boundedDiagnostic(
        mailRecord.payload.diagnostic,
        mailRecord.payload,
        mailRecord.payload.citations,
      );
      assert.equal(bounded.mcp.call_count, 2);
      assert.deepEqual(bounded.mcp.status, ['ok', mailStatus]);
      for (const classifier of [classify, browserClassify]) {
        const classified = classifier('mail', mailRecord, mailTurn);
        assert.notEqual(classified.status, 'mail_cited_result');
        assert.equal(classified.visible_text_pass, false);
        let capturedMail = '';
        process.stdout.write = chunk => { capturedMail += chunk; return true; };
        try {
          safeOutput(classified);
        } finally {
          process.stdout.write = originalWrite;
        }
        const safeMail = JSON.parse(capturedMail);
        assert.equal(safeMail.tool_count, 2);
        assert.equal(safeMail.diagnostic.mcp.call_count, 2);
        assert.deepEqual(safeMail.diagnostic.mcp.status, ['ok', mailStatus]);
        assert.notEqual(safeMail.status, 'mail_cited_result');
        assert.equal(capturedMail.includes(privateMarker), false);
      }
    }
  }

  let mcpFailureCaptured = '';
  process.stdout.write = chunk => {
    mcpFailureCaptured += chunk;
    return true;
  };
  try {
    safeOutput(mcpFailureResult);
  } finally {
    process.stdout.write = originalWrite;
  }
  const safeMcpFailureOutput = JSON.parse(mcpFailureCaptured);
  assert.equal(
    safeMcpFailureOutput.diagnostic.mcp.response_stage,
    'jsonrpc_error',
  );
  assert.deepEqual(
    safeMcpFailureOutput.diagnostic.mcp.request_discriminator,
    mcpFailureResult.diagnostic.mcp.request_discriminator,
  );
  assert.equal(mcpFailureCaptured.includes(privateMarker), false);

  const malformedMcpFailure = JSON.parse(JSON.stringify(mcpFailureRecord));
  malformedMcpFailure.payload.diagnostic.mcp.request_discriminator = {
    tool_name: 'query_mail_evidence',
    selector_kind: 'mail_import_session_id',
    selector_present: true,
    selector_count: 1,
    selector_hash: 'raw-selector',
  };
  malformedMcpFailure.payload.diagnostic.mcp.response_stage = 'private_stage';
  const malformedMcpResult = classify('mail', malformedMcpFailure, {
    status: 'error',
    text: '查詢失敗，請稍後再試。',
    visible: true,
    error: '',
    citations: 0,
  });
  assert.equal(
    Object.hasOwn(malformedMcpResult.diagnostic.mcp, 'request_discriminator'),
    false,
  );
  assert.equal(
    Object.hasOwn(malformedMcpResult.diagnostic.mcp, 'response_stage'),
    false,
  );
  const mcpNoDataRecord = JSON.parse(JSON.stringify(mcpFailureRecord)); mcpNoDataRecord.payload.status = 'complete';
  mcpNoDataRecord.payload.answer = '沒有找到任何信件。';
  const mcpNoDataResult = classify('mail', mcpNoDataRecord, {status: 'complete', text: mcpNoDataRecord.payload.answer, visible: true, error: '', citations: 0});
  assert.equal(mcpNoDataResult.status, 'mail_unsafe_failure');
  const makeMcpReasonRecord = failureReason => ({
    record: {
      http: 200,
      payload: {
        status: 'error',
        answer: '查詢失敗，請稍後再試。',
        citations: [],
        diagnostic: {
          mcp: {
            call_count: 1,
            elapsed_ms: 12,
            status: ['mcp_failed'],
            timeout: false,
            failure_reason: failureReason,
          },
        },
      },
    },
    turn: {
      status: 'error',
      text: '查詢失敗，請稍後再試。',
      visible: true,
      error: '',
      citations: 0,
    },
  });
  for (const failureReason of safeMcpFailureReasonCodes) {
    const known = makeMcpReasonRecord(failureReason);
    const bounded = boundedDiagnostic(
      known.record.payload.diagnostic,
      known.record.payload,
      [],
    );
    assert.equal(bounded.mcp.failure_reason, failureReason);
    const browserResult = browserClassify('mail', known.record, known.turn);
    assert.equal(browserResult.diagnostic.mcp.failure_reason, failureReason);
    const nodeResult = classify('mail', known.record, known.turn);
    assert.equal(nodeResult.diagnostic.mcp.failure_reason, failureReason);
    let reasonCaptured = '';
    process.stdout.write = chunk => {
      reasonCaptured += chunk;
      return true;
    };
    try {
      safeOutput(browserResult);
    } finally {
      process.stdout.write = originalWrite;
    }
    const safeReasonOutput = JSON.parse(reasonCaptured);
    assert.equal(
      safeReasonOutput.diagnostic.mcp.failure_reason,
      failureReason,
    );
  }
  const unknownReason = 'unknown_private_failure_reason';
  const unknown = makeMcpReasonRecord(unknownReason);
  const boundedUnknown = boundedDiagnostic(
    unknown.record.payload.diagnostic,
    unknown.record.payload,
    [],
  );
  assert.equal(boundedUnknown.mcp.failure_reason, null);
  const browserUnknown = browserClassify('mail', unknown.record, unknown.turn);
  assert.equal(browserUnknown.diagnostic.mcp.failure_reason, null);
  const nodeUnknown = classify('mail', unknown.record, unknown.turn);
  assert.equal(nodeUnknown.diagnostic.mcp.failure_reason, null);
  let unknownCaptured = '';
  process.stdout.write = chunk => {
    unknownCaptured += chunk;
    return true;
  };
  try {
    safeOutput(browserUnknown);
  } finally {
    process.stdout.write = originalWrite;
  }
  const safeUnknownOutput = JSON.parse(unknownCaptured);
  assert.equal(safeUnknownOutput.diagnostic.mcp.failure_reason, null);
  assert.equal(unknownCaptured.includes(unknownReason), false);
  const timedOutState = createRunnerState();
  recordRunnerFailure(
    timedOutState,
    'cdp_timeout',
    'page_navigation',
    'Page.navigate',
  );
  timedOutState.phase = 'cleanup';
  const timedOutDiagnostic = boundedRunnerDiagnostic(timedOutState);
  assert.equal(timedOutDiagnostic.phase, 'page_navigation');
  assert.equal(timedOutDiagnostic.cdp_error, 'cdp_timeout');
  assert.equal(timedOutDiagnostic.cdp_command, 'Page.navigate');
  const crashState = createRunnerState();
  noteBrowserStderr(crashState,
    Buffer.from('FATAL crash at /private/secret/path\n'));
  recordRunnerFailure(crashState, classifyPipeFailure({code: 'ECONNRESET'}),
    'cdp_connect');
  crashState.browser_exit_code = 1;
  crashState.browser_signal = 'SIGABRT';
  let crashCaptured = '';
  process.stdout.write = chunk => { crashCaptured += chunk; return true; };
  try {
    safeOutput({status: 'runner_error', runner_diagnostic: crashState});
  } finally {
    process.stdout.write = originalWrite;
  }
  assert.equal(crashCaptured.includes('/private/'), false);
  assert.equal(crashCaptured.includes('secret'), false);
  const safeCrashOutput = JSON.parse(crashCaptured);
  assert.equal(safeCrashOutput.runner_diagnostic.failure_reason, 'pipe_reset');
  assert.equal(safeCrashOutput.runner_diagnostic.cdp_error, 'pipe_reset');
  assert.equal(safeCrashOutput.runner_diagnostic.browser_exit_code, 1);
  assert.equal(safeCrashOutput.runner_diagnostic.browser_signal, 'SIGABRT');
  assert.deepEqual(safeCrashOutput.runner_diagnostic.stderr_categories, ['crash']);
  record.http = 503;
  turn.status = record.payload.status = 'error';
  turn.text = '來源查詢失敗，請稍後再試。';
  turn.citations = 0;
  assert.equal(classify('mail', record, turn).status, 'mail_operational_failure');
  turn.text = '沒有找到任何信件。';
  assert.equal(classify('mail', record, turn).status, 'mail_unsafe_failure');
  safeOutput({status: 'tooling_self_check_passed'});
}

Promise.resolve().then(async () => {
  if (process.argv.includes('--self-check')) await selfCheck();
  else if (!process.argv.includes('--live')) safeOutput({status: 'awaiting_master_go'});
  else process.exitCode = await main();
}).catch(() => {
  if (!runnerOutputEmitted) {
    safeOutput({status: 'runner_error', runner_diagnostic: lastRunnerState},
      {final: true});
  }
  process.exitCode = 1;
});
