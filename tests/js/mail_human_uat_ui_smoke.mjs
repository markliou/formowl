import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(
  new URL("../../python/formowl_mail/human_uat_http.py", import.meta.url),
  "utf8",
);

class FakeClassList {
  constructor(initial = []) {
    this.values = new Set(initial);
  }

  add(...names) {
    for (const name of names) this.values.add(name);
  }

  remove(...names) {
    for (const name of names) this.values.delete(name);
  }

  contains(name) {
    return this.values.has(name);
  }

  toggle(name, force) {
    if (force === true) {
      this.values.add(name);
      return true;
    }
    if (force === false) {
      this.values.delete(name);
      return false;
    }
    if (this.values.has(name)) {
      this.values.delete(name);
      return false;
    }
    this.values.add(name);
    return true;
  }
}

class FakeElement {
  constructor(tagName = "div", initialClasses = []) {
    this.tagName = tagName;
    this.classList = new FakeClassList(initialClasses);
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.dataset = {};
    this.value = "";
    this.files = [];
    this.disabled = false;
    this.textContent = "";
    this.contentWindow = null;
    this.focused = false;
    this.removed = false;
  }

  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  append(...children) {
    this.children.push(...children);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    this.children = [...children];
    this.textContent = "";
  }

  querySelectorAll(selector) {
    if (selector !== ".message") return [];
    return this.children.filter(
      (child) => typeof child.className === "string" && child.className.includes("message"),
    );
  }

  focus() {
    this.focused = true;
  }

  remove() {
    this.removed = true;
  }

  async dispatch(name, values = {}) {
    const event = {
      target: this,
      currentTarget: this,
      preventDefault() {},
      ...values,
    };
    for (const listener of this.listeners.get(name) || []) {
      await listener(event);
    }
    return event;
  }
}

class FakeFormData {
  constructor() {
    this.entries = [];
  }

  append(...entry) {
    this.entries.push(entry);
  }
}

function extractScript(constantName) {
  const marker = `${constantName} = """`;
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, `${constantName} must exist`);
  const htmlStart = start + marker.length;
  const htmlEnd = source.indexOf('\n"""', htmlStart);
  assert.notEqual(htmlEnd, -1, `${constantName} must terminate`);
  const html = source.slice(htmlStart, htmlEnd);
  const match = html.match(/<script>([\s\S]*?)<\/script>/u);
  assert.ok(match, `${constantName} must contain an inline script`);
  return match[1];
}

function textTree(node) {
  return [node.textContent, ...node.children.map(textTree)].join(" ");
}

function tagTree(node, tagName) {
  return [
    ...(node.tagName === tagName ? [node] : []),
    ...node.children.flatMap((child) => tagTree(child, tagName)),
  ];
}

function makeDocument(ids) {
  const elements = new Map();
  for (const id of ids) {
    elements.set(
      id,
      new FakeElement("div", id === "upload-modal" ? ["hidden"] : []),
    );
  }
  const body = new FakeElement("body");
  body.scrollHeight = 1200;
  const document = {
    body,
    getElementById(id) {
      assert.ok(elements.has(id), `unexpected element id: ${id}`);
      return elements.get(id);
    },
    createElement(tagName) {
      return new FakeElement(tagName);
    },
  };
  return { document, elements };
}

function makeWindow(origin = "http://formowl.test") {
  const listeners = new Map();
  let randomCallCount = 0;
  const makeStorage = () => {
    const values = new Map();
    return {
      getItem(key) {
        return values.get(key) || null;
      },
      setItem(key, value) {
        values.set(key, value);
      },
    };
  };
  const window = {
    innerWidth: 1280,
    location: { origin },
    localStorage: makeStorage(),
    sessionStorage: makeStorage(),
    crypto: {
      getRandomValues(bytes) {
        randomCallCount += 1;
        for (let index = 0; index < bytes.length; index += 1) {
          bytes[index] = index + randomCallCount;
        }
        return bytes;
      },
    },
    parent: null,
    scrollTo() {},
    setTimeout,
    clearTimeout,
    addEventListener(name, listener) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(listener);
    },
    async dispatch(name, event) {
      for (const listener of listeners.get(name) || []) {
        await listener(event);
      }
    },
  };
  window.parent = window;
  return window;
}

function response(payload, ok = true, status = ok ? 200 : 400) {
  return {
    ok,
    status,
    async json() {
      return payload;
    },
  };
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function runChatSmoke() {
  const { document, elements } = makeDocument([
    "conversation",
    "upload-modal",
    "upload-frame",
    "send",
    "chat-input",
    "open-upload",
    "close-upload",
    "new-chat",
    "upload-count",
    "server-status",
    "status-copy",
    "current-chat-title",
    "sidebar-toggle",
    "mobile-menu",
    "sidebar-overlay",
    "brand-home",
    "search-conversations",
    "model-selector",
    "tools-control",
    "profile-card",
    "top-avatar",
    "shell-toast",
  ]);
  const frameWindow = {};
  elements.get("upload-frame").contentWindow = frameWindow;
  const window = makeWindow();
  const requests = [];
  let queryShouldFail = false;
  const fetch = async (path, options = {}) => {
    requests.push({ path, options });
    if (path === "/api/health") {
      return response({ status: "ready" });
    }
    if (path === "/api/session-summary") {
      return response({ uploaded_file_count: 2 });
    }
    if (path === "/api/chat") {
      if (queryShouldFail) {
        return response({ error_code: "request_failed" }, false, 500);
      }
      return response({
        status: "ok",
        query_id: "uatquery_111111111111111111111111",
        assistant_text: "這是一個不需要搜尋來源的直接回答。",
        result_count: 0,
        total_result_count: 0,
        displayed_result_count: 0,
        results: [],
        orchestration: {
          action: "answer_without_tool",
          formowl_tool_called: false,
        },
        projection: {},
      });
    }
    if (path === "/api/feedback") {
      return response({ status: "recorded" });
    }
    if (path === "/api/interaction") {
      return response({ status: "recorded" });
    }
    throw new Error(`unexpected fetch path: ${path}`);
  };
  const context = vm.createContext({
    Array,
    Error,
    FormData: FakeFormData,
    JSON,
    Math,
    Number,
    Promise,
    Uint8Array,
    console,
    document,
    fetch,
    setTimeout,
    window,
  });
  vm.runInContext(extractScript("_CHAT_UAT_HTML"), context);
  await settle();
  requests.length = 0;

  await elements.get("open-upload").dispatch("click");
  assert.equal(elements.get("upload-modal").classList.contains("hidden"), false);
  assert.equal(elements.get("upload-frame").focused, true);
  let interactionRequest = requests.find((item) => item.path === "/api/interaction");
  assert.ok(interactionRequest);
  assert.equal(JSON.parse(interactionRequest.options.body).action, "upload_open");

  const messageCountBeforeRejects = elements.get("conversation").children.length;
  await window.dispatch("message", {
    origin: "https://attacker.example",
    source: frameWindow,
    data: { type: "formowl-upload-complete", accepted_file_count: 9 },
  });
  assert.equal(elements.get("upload-modal").classList.contains("hidden"), false);
  assert.equal(elements.get("conversation").children.length, messageCountBeforeRejects);

  await window.dispatch("message", {
    origin: window.location.origin,
    source: {},
    data: { type: "formowl-upload-complete", accepted_file_count: 9 },
  });
  assert.equal(elements.get("upload-modal").classList.contains("hidden"), false);
  assert.equal(elements.get("conversation").children.length, messageCountBeforeRejects);

  await window.dispatch("message", {
    origin: window.location.origin,
    source: frameWindow,
    data: {
      type: "formowl-upload-complete",
      accepted_file_count: 2,
      indexed_item_count: 37,
    },
  });
  await settle();
  assert.equal(elements.get("upload-modal").classList.contains("hidden"), true);
  assert.match(textTree(elements.get("conversation")), /已加入 2 個檔案/u);
  assert.match(textTree(elements.get("conversation")), /37 個可搜尋項目/u);
  assert.equal(document.body.classList.contains("has-conversation"), true);

  requests.length = 0;
  await context.ask("最近一次文顥的量產時間");
  let queryRequest = requests.find((item) => item.path === "/api/chat");
  assert.ok(queryRequest);
  let queryPayload = JSON.parse(queryRequest.options.body);
  assert.equal("sort" in queryPayload, false);
  assert.equal("limit" in queryPayload, false);
  assert.equal(queryPayload.source, "composer");
  assert.match(queryPayload.visitor_id, /^uatvisitor_[0-9a-f]{32}$/u);
  assert.match(queryPayload.session_id, /^uatsession_[0-9a-f]{32}$/u);
  assert.equal(Number.isSafeInteger(queryPayload.sequence), true);
  const initialSessionId = queryPayload.session_id;

  requests.length = 0;
  await context.ask("PO 470002154");
  queryRequest = requests.find((item) => item.path === "/api/chat");
  assert.ok(queryRequest);
  assert.equal(JSON.parse(queryRequest.options.body).query_text, "PO 470002154");

  const tableHolder = new FakeElement("div");
  context.renderAssistantResult(
    {
      query_id: "uatquery_222222222222222222222222",
      assistant_text: "以下是來源證據的整理結果。",
      total_result_count: 12,
      displayed_result_count: 2,
      results: [
        {
          snippet: "最重要的來源內容",
          subject: "次要主旨",
          sent_at: "2026-07-20T08:00:00+00:00",
          source_kind: "preloaded",
          citation: { citation_id: "mailcitation_table" },
        },
        {
          snippet: "第二筆來源內容",
          subject: "第二筆主旨",
          sent_at: null,
          source_kind: "uploaded_uat",
          citation: null,
        },
      ],
      notice: "內容優先",
      orchestration: {
        action: "render_prior_evidence",
        formowl_tool_called: false,
      },
      projection: { output_format: "table" },
    },
    tableHolder,
  );
  assert.match(textTree(tableHolder), /共找到 12 筆/u);
  assert.match(textTree(tableHolder), /目前顯示 2 筆/u);
  assert.equal(tagTree(tableHolder, "table").length, 1);
  assert.equal(tagTree(tableHolder, "th")[0].textContent, "內容");
  assert.doesNotMatch(textTree(tableHolder), /寄件者|收件者/u);

  const narrativeHolder = new FakeElement("div");
  context.renderAssistantResult(
    {
      query_id: "uatquery_333333333333333333333333",
      assistant_text: "以下是來源內容。",
      total_result_count: 1,
      displayed_result_count: 1,
      results: [
        {
          snippet: "內容先出現",
          subject: "主旨後出現",
          sent_at: "2026-07-20T08:00:00+00:00",
          source_kind: "preloaded",
          citation: null,
        },
      ],
      notice: "內容優先",
      orchestration: {
        action: "call_formowl_tool",
        formowl_tool_called: true,
      },
      projection: { output_format: "narrative" },
    },
    narrativeHolder,
  );
  const evidenceCard = tagTree(narrativeHolder, "article")[0];
  assert.equal(evidenceCard.children[0].tagName, "p");
  assert.equal(evidenceCard.children[0].textContent, "內容先出現");
  assert.equal(evidenceCard.children[1].tagName, "h3");

  requests.length = 0;
  await elements.get("sidebar-toggle").dispatch("click");
  assert.equal(document.body.classList.contains("sidebar-collapsed"), true);
  interactionRequest = requests.find((item) => item.path === "/api/interaction");
  assert.equal(JSON.parse(interactionRequest.options.body).action, "sidebar_toggle");

  requests.length = 0;
  await elements.get("tools-control").dispatch("click");
  interactionRequest = requests.find((item) => item.path === "/api/interaction");
  assert.equal(JSON.parse(interactionRequest.options.body).action, "shell_control");
  assert.equal(
    JSON.parse(interactionRequest.options.body).details.control,
    "tools_menu",
  );
  assert.match(elements.get("shell-toast").textContent, /資料上傳與證據查詢/u);
  assert.equal(elements.get("shell-toast").classList.contains("visible"), true);

  requests.length = 0;
  await elements.get("brand-home").dispatch("click");
  interactionRequest = requests.find((item) => item.path === "/api/interaction");
  assert.equal(
    JSON.parse(interactionRequest.options.body).details.control,
    "brand_home",
  );
  const brandHomeNewChatRequest = requests.find((item) => {
    if (item.path !== "/api/interaction") return false;
    return JSON.parse(item.options.body).action === "new_chat";
  });
  assert.ok(brandHomeNewChatRequest);
  assert.equal(
    JSON.parse(brandHomeNewChatRequest.options.body).session_id,
    initialSessionId,
  );
  const brandHomeSessionId = window.sessionStorage.getItem(
    "formowl_uat_session_id",
  );
  assert.match(brandHomeSessionId, /^uatsession_[0-9a-f]{32}$/u);
  assert.notEqual(brandHomeSessionId, initialSessionId);
  assert.equal(document.body.classList.contains("has-conversation"), false);
  assert.equal(elements.get("current-chat-title").textContent, "新對話");

  requests.length = 0;
  elements.get("chat-input").value = "最近的交期";
  await elements.get("chat-input").dispatch("keydown", {
    key: "Enter",
    shiftKey: false,
    isComposing: true,
  });
  await settle();
  assert.equal(requests.some((item) => item.path === "/api/chat"), false);

  await elements.get("chat-input").dispatch("keydown", {
    key: "Enter",
    shiftKey: false,
    isComposing: false,
  });
  await settle();
  queryRequest = requests.find((item) => item.path === "/api/chat");
  assert.ok(queryRequest);
  assert.equal(
    JSON.parse(queryRequest.options.body).session_id,
    brandHomeSessionId,
  );

  requests.length = 0;
  await elements.get("new-chat").dispatch("click");
  const newChatRequest = requests.find((item) => {
    if (item.path !== "/api/interaction") return false;
    return JSON.parse(item.options.body).action === "new_chat";
  });
  assert.ok(newChatRequest);
  assert.equal(
    JSON.parse(newChatRequest.options.body).session_id,
    brandHomeSessionId,
  );
  const rotatedSessionId = window.sessionStorage.getItem(
    "formowl_uat_session_id",
  );
  assert.match(rotatedSessionId, /^uatsession_[0-9a-f]{32}$/u);
  assert.notEqual(rotatedSessionId, brandHomeSessionId);
  assert.equal(document.body.classList.contains("has-conversation"), false);
  assert.equal(elements.get("current-chat-title").textContent, "新對話");

  window.innerWidth = 600;
  document.body.classList.add("mobile-sidebar-open");
  await elements.get("current-chat-title").dispatch("click");
  assert.equal(document.body.classList.contains("mobile-sidebar-open"), false);

  requests.length = 0;
  queryShouldFail = true;
  await context.ask("模擬查詢失敗");
  queryRequest = requests.find((item) => item.path === "/api/chat");
  assert.ok(queryRequest);
  assert.equal(
    JSON.parse(queryRequest.options.body).session_id,
    rotatedSessionId,
  );
  assert.match(textTree(elements.get("conversation")), /回覆暫時失敗/u);
  assert.equal(elements.get("send").disabled, false);
  assert.equal(
    requests.some((item) => {
      if (item.path !== "/api/interaction") return false;
      return JSON.parse(item.options.body).action === "query_error";
    }),
    true,
  );
}

async function runUploadSmoke() {
  const { document, elements } = makeDocument([
    "mail-files",
    "drop",
    "files",
    "message",
    "upload",
    "cancel",
  ]);
  const posted = [];
  const window = makeWindow();
  window.parent = {
    postMessage(payload, targetOrigin) {
      posted.push({ payload, targetOrigin });
    },
  };
  const requests = [];
  let uploadShouldFail = false;
  const fetch = async (path, options = {}) => {
    requests.push({ path, options });
    if (path === "/api/interaction") {
      return response({ status: "recorded" });
    }
    assert.equal(path, "/api/upload");
    if (uploadShouldFail) {
      return response({ error_code: "request_failed" }, false, 500);
    }
    return response({
      accepted_file_count: 1,
      duplicate_file_count: 0,
      indexed_item_count: 1,
    });
  };
  const context = vm.createContext({
    Array,
    Error,
    FormData: FakeFormData,
    Math,
    Promise,
    Uint8Array,
    console,
    document,
    fetch,
    setTimeout,
    window,
  });
  vm.runInContext(extractScript("_UPLOAD_IFRAME_HTML"), context);

  context.selectFiles([{ name: "too-large.pdf", size: 25 * 1024 * 1024 + 1 }]);
  assert.match(elements.get("message").textContent, /其他格式單檔不可超過 25 MB/u);
  assert.equal(elements.get("message").classList.contains("error"), true);
  assert.equal(
    JSON.parse(requests.at(-1).options.body).details.reason,
    "file_size",
  );

  context.selectFiles([
    { name: "one.pst", size: 300 * 1024 * 1024 },
    { name: "two.pst", size: 300 * 1024 * 1024 },
  ]);
  assert.match(elements.get("message").textContent, /合計不可超過 500 MB/u);

  context.selectFiles([{ name: "unsupported.msg", size: 1024 }]);
  assert.match(elements.get("message").textContent, /EML、PST、PDF、TXT/u);

  context.selectFiles([{ name: "valid.pdf", size: 1024 }]);
  assert.match(elements.get("message").textContent, /已選擇 1 個檔案/u);
  uploadShouldFail = true;
  await elements.get("upload").dispatch("click");
  assert.match(elements.get("message").textContent, /上傳失敗/u);
  assert.equal(elements.get("upload").disabled, false);

  uploadShouldFail = false;
  await elements.get("upload").dispatch("click");
  const uploadRequest = requests.find((item) => item.path === "/api/upload");
  assert.ok(uploadRequest);
  assert.equal(uploadRequest.options.body.entries.length, 1);
  assert.equal(posted.at(-1).payload.type, "formowl-upload-complete");
  assert.equal(posted.at(-1).payload.accepted_file_count, 1);
  assert.equal(posted.at(-1).payload.duplicate_file_count, 0);
  assert.equal(posted.at(-1).payload.indexed_item_count, 1);
  assert.equal(posted.at(-1).targetOrigin, window.location.origin);
  assert.equal(elements.get("files").children.length, 0);
  assert.equal(elements.get("mail-files").value, "");

  await elements.get("cancel").dispatch("click");
  assert.equal(posted.at(-1).payload.type, "formowl-upload-close");
  assert.equal(posted.at(-1).targetOrigin, window.location.origin);
}

await runChatSmoke();
await runUploadSmoke();
console.log("mail human UAT UI smoke: OK");
