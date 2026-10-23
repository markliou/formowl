"""Deterministic, fail-closed semantic query plans for Issue #56 POC execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Mapping, Sequence
import unicodedata

from formowl_contract import (
    CORE_SUPERTYPE_IDS,
    ContractValidationError,
    PermissionScope,
    sha256_json,
    to_plain,
    validate_permission_scope,
)
from formowl_graph import EffectiveGraphView
from formowl_core.tokenization import _protected_identifier_spans

from ._guards import assert_public_payload_safe, safe_public_string

SEMANTIC_QUERY_CLASSES = (
    "evidence_lookup",
    "relation_reasoning",
    "exact_set_or_inventory",
    "global_summarization",
)
AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND = "authorized_mail_observation"
GITHUB_PROJECT_OBSERVATION_SOURCE_KIND = "github_project_observation"
AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND = "authorized_text_observation"
AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND = "authorized_multisource_observation"
_SOURCE_OCCURRENCE_SCHEMA_BY_KIND = {
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND: "mail_message_occurrence_v1",
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND: "github_issue_comment_occurrence_v1",
    AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND: "document_text_line_occurrence_v1",
    AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND: "mail_text_occurrence_union_v1",
}
_SOURCE_KIND_MEMBERS_BY_KIND = {
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND: (AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,),
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND: (GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,),
    AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND: (AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,),
    AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND: (
        AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
        AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
    ),
}
SEMANTIC_CLAIM_STRENGTH_BY_CLASS = {
    "evidence_lookup": "cited_evidence",
    "relation_reasoning": "bounded_relation",
    "exact_set_or_inventory": "complete_authorized_scope",
    "global_summarization": "bounded_summary",
}

# The current request boundary can include mail, attachment tables, and
# independent document text together. Capability validation still owns access.
SEMANTIC_REQUEST_MAX_SOURCE_FAMILIES = 3
_CLAIM_STRENGTH_BY_CLASS = SEMANTIC_CLAIM_STRENGTH_BY_CLASS
_SEMANTIC_REQUEST_CONTRACT_FIELDS = {
    "original_query_hash",
    "query_class",
    "source_family_scope",
    "requested_fields",
    "maximum_claim_strength",
}
EXACT_QUERY_GRAMMAR_ROLES = (
    "conjunction",
    "operator",
    "particle",
    "preposition",
    "pronoun",
    "verb",
)
_EXACT_QUERY_LEXICAL_ROLES = {
    "filter_value",
    "projection_field",
}
_PERMISSION_REQUIREMENTS_BY_CLASS = {
    "evidence_lookup": ("evidence_snippet",),
    "relation_reasoning": ("evidence_snippet", "graph_snippet"),
    "exact_set_or_inventory": ("evidence_snippet", "graph_snippet"),
    "global_summarization": ("evidence_snippet",),
}
_EXACT_TERMS = (
    "count",
    "exact set",
    "inventory",
    "list all",
    "how many",
    "全部",
    "清單",
    "盤點",
    "多少",
    "哪些",
    "明細",
)
_CJK_EXACT_OUTPUT_GRAMMAR_V1 = (
    ("列出", "列舉", "調閱", "整理"),
    ("出來",),
    ("全部", "都", "所有", "每"),
)
_CJK_RECORD_CLASSIFIERS = "封筆笔個个件份條条項项行列"
# A separate citation-presentation clause does not quantify the source records
# requested by the preceding lookup. Keep record inventories/counts intact.
_CITATION_PRESENTATION_SUFFIX = re.compile(
    r"(?:[,;.!?，；。]|\band\b)\s*(?:please\s+)?"
    r"(?:(?:list|show|include|provide|列出|附上|提供)\s*"
    r"(?:(?:all|the|所有|全部)\s*)?(?:source\s+)?"
    r"(?:citations?|references?|來源引用|引用來源|來源出處|來源連結)"
    r"|cite\s+(?:(?:each|every|all|the)\s+)?(?:facts?|claims?|statements?|sources?|evidence))"
    r"\s*[.!。！]?$"
)
_EXPLICIT_CITATION_REQUEST_SUFFIX = re.compile(
    r"(?:引用(?:付き(?:で(?:(?:説明|回答)して|教えて)ください)?|を(?:示し|付け)てください)"
    # Anchor the positive directive to a clause; never match inside 不要提供引用.
    r"|(?:^|[,;。.!?])\s*[請请]?\s*提供\s*(?:[來来]源)?引用)\s*[。.!?]?$"
)
_NEGATED_COMPLETENESS_DIRECTIVE = re.compile(
    r"(?:請)?(?:不要|請勿|別|别)"
    r"(?:(?:說|说|宣稱|聲稱|表示|標示|标示)這(?:些)?(?:結果)?(?:是|為)"
    r"(?:全部|所有|完整(?:清單|盤點)?)"
    r"|(?:列出|列舉)(?:全部|所有)(?:郵件|信件|文件|紀錄|記錄|附件|資料))"
    r"|(?:please\s+)?(?:do not|don['’]t|never)\s+"
    r"(?:(?:say|claim|state|call)\s+(?:that\s+)?(?:this|these(?:\s+results)?|the results)\s+"
    r"(?:(?:is|are)\s+)?(?:(?:a|an|the)\s+)?"
    r"(?:exact set|complete inventory|complete list|all\s+(?:records|messages|documents))"
    r"|list all\s+(?:records|messages|documents))"
    r"|(?:請|请)?(?:不|不要|勿)(?:加總|加总|合計|合计)"
    r"|(?:請|请)?(?:不|不要|勿)(?:推論|推断|推斷)(?:所有|全部)"
    r"(?!(?:[^,;，；、。.!?！？]*)(?:並|并|但|另|再|請|请|列出|計算|计算|統計|统计|查))"
    r"[\u4e00-\u9fff]{1,24}"
    r"|(?:please\s+)?(?:do not|don't)\s+(?:infer|extrapolate)\s+(?:all|every)\s+"
    r"(?!(?:[^,;，；、。.!?！？]*\b)(?:and|but|then|also|count|list|calculate|find)\b)"
    r"[a-z]+(?:\s+[a-z]+){0,2}"
)
# Match quoted spans first so their contents never become output directives.
# Only a closed conditional disclosure clause is excluded from classification;
# affirmative operations and negative source predicates remain untouched.
_CONDITIONAL_COMPLETENESS_DISCLOSURE = re.compile(
    r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|(?<!\w)\x27[^\x27]*\x27(?!\w)'
    r"|(?P<disclosure>(?<![^,;，；。.!?？])\s*(?:"
    r"(?:若|如果)(?:無法|不能)(?:證明|確認|保證)"
    r"(?:完整(?:清單|盤點)|完整性)\s*[,，]?\s*"
    r"(?:請)?(?:說明|註明)(?:限制|原因)?"
    r"|if\s+(?:you\s+)?cannot\s+(?:certify|prove|verify)\s+"
    r"(?:(?:a|the)\s+complete\s+(?:inventory|list)|completeness)"
    r"\s*[,，]?\s*(?:please\s+)?"
    r"(?:say\s+so|(?:state|disclose)\s+the\s+limitation)"
    r")\s*(?=$|[,;，；。.!?？]))"
)
_GREETING_MARKERS = ("hello", "hi", "hey", "嗨", "你好", "您好")
# Closed language modifiers, not arbitrary adjectives that could hide a lookup.
_TEXT_TASK_CJK_LANGUAGE = (
    r"(?:(?:台灣|臺灣|台湾|香港)?(?:繁體|繁体|簡體|简体)?中文|"
    r"(?:英式|美式)?英文|日文|法文|德文|西班牙文)"
)
_TEXT_TASK_EN_LANGUAGE = (
    r"(?:(?:traditional|simplified)\s+chinese|(?:british|american)\s+english|[a-z]{2,20})"
)
_TEXT_TASK_INSTRUCTION = re.compile(
    r"(?:(?:please\s+)?(?:only\s+)?(?:translate|rewrite|rephrase|proofread|summarize|summarise)"
    r"(?:\s+(?:only\s+)?(?:(?:this|the(?: following)?|following)\s+)?"
    r"(?:(?:provided|supplied)\s+)?"
    r"(?:sentence|text|paragraph|message)(?:\s+(?:that\s+)?i\s+(?:(?:now|currently)\s+)?"
    r"(?:provide|supply|paste)(?:\s+now)?)?)?"
    rf"(?:\s+(?:(?:into|in|to)\s+{_TEXT_TASK_EN_LANGUAGE}|more\s+(?:politely|formally|concisely)"
    r"|in\s+(?:a\s+)?(?:polite|formal|concise)\s+(?:tone|style)))?"
    r"|(?:請|请)?(?:只|僅|仅)?(?:幫我|帮我)?"
    r"(?:(?:翻譯|翻译|翻|改寫|改写|潤飾|润色|校對|校对|摘要)"
    r"(?:這|这|以下|提供的|我(?:現在|现在)?(?:提供|貼上|贴上)的)?"
    r"(?:句話|句话|句|段文字|段話|段话|文字)?"
    r"|把(?:這|这|以下)(?:句話|句话|句|段文字|段話|段话|文字)(?:翻譯|翻译|改寫|改写))"
    rf"(?:(?:成|為|为)(?:自然|流暢|流畅)?{_TEXT_TASK_CJK_LANGUAGE})?)"
    r"(?:[,;]\s*(?:不用查資料|不用查资料|不需查資料|do not look up data|without lookup))?"
)
_LITERAL_SCALAR = r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
_COUNT_UNITS = r"(?:one|two|three|four|five|six|seven|eight|nine)"
_LITERAL_COUNT = (
    rf"(?:[0-9]+|[零〇一二兩两三四五六七八九十百千]+|{_COUNT_UNITS}"
    r"|zero|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
    rf"|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ]{_COUNT_UNITS})?)"
)
_OUTPUT_SEPARATOR = r"(?:comma|semicolon|space|newline)"
_OUTPUT_DIRECTIVE = r"(?:(?:reply|respond)\s+with|answer|return|output)"
_OUTPUT_VALUE = r"(?:the\s+)?(?:numbers?|results?|answer|translation|list)"
_LIST_COUNT_POLICY_CLAUSE = (
    r"(?:重複|重复)(?:項目|项目)(?:也要|也需)(?:計算|计算)"
    r"|(?:count|include|including|excluding|counting)\s+"
    r"(?:(?:duplicate|repeated)\s+items|duplicates)(?:\s+too)?"
)
_TEXT_PRESERVED_VALUE = r"(?:識別碼|标识符|識別符|日期|時間|时间|單位|单位|數值|数值)"
_TEXT_OUTPUT_FORMAT_CLAUSE = (
    r"(?:以|用)(?:逗號|逗号|分號|分号|空格|換行|换行)(?:(?:和|與|与|及|、)(?:逗號|逗号|分號|分号|空格|換行|换行))*(?:分隔|隔開|隔开)"
    r"|(?:請|请)?只(?:回答|回覆|回复|回傳|回传|輸出|输出)(?:(?:排序|計數|计数|統計|统计|去重|翻譯|翻译)?結果|结果|數字|数字|數量|数量|譯文|译文)"
    rf"|(?:please\s+)?(?:(?:(?:only|just)\s+{_OUTPUT_DIRECTIVE}"
    rf"|{_OUTPUT_DIRECTIVE}\s+(?:only|just))\s+{_OUTPUT_VALUE}"
    rf"|{_OUTPUT_DIRECTIVE}\s+{_OUTPUT_VALUE}\s+only)"
    rf"|(?:please\s+)?(?:use|using|separated\s+by)\s+{_OUTPUT_SEPARATOR}s?"
    rf"|{_OUTPUT_SEPARATOR}[- ]separated"
    rf"|(?:please\s+)?separate\s+(?:the\s+)?(?:items|copies|results)\s+with\s+{_OUTPUT_SEPARATOR}s?"
    rf"|(?:請|请)?保留{_TEXT_PRESERVED_VALUE}(?:[、和及與与]{_TEXT_PRESERVED_VALUE})*"
    r"|(?:please\s+)?(?:preserve|retain|keep)\s+(?:identifiers|dates|times|units|values)"
    r"(?:(?:,\s*(?:and\s+)?|\s+and\s+)(?:identifiers|dates|times|units|values))*"
)

_PRIOR_PRESENTATION = re.compile(
    r"(?:please\s+)?(?:reformat|rewrite|translate|summarize)\s+the\s+above"
    r"(?:\s+(?:in|as|into)\s+(?:a\s+)?(?:table|list|summary|english|chinese))?[.!]?"
    r"|(?:請)?(?:整理|改寫|翻譯|重新格式化)上面的"
    r"(?:引用證據|證據|引用|文字|內容|結果|報告)?[。]?"
)
# Refer to a retained value/label, not an identifier or a fresh source query.
# Alternatives are label interpretations; no business-property vocabulary is used.
_PRIOR_INTERPRETATION = re.compile(
    r"(?:please\s+)?(?:explain|clarify)\s+(?:the\s+)?meaning\s+of\s+"
    r"(?:the\s+)?(?:cited|above)\s+[^:;.!?]+[.!?]?"
    r"|(?:does|is)\s+(?:this|that|the cited|the above)\s+"
    r"(?:date|time|value|number|field|label)\s+"
    r"(?:(?:mean|represent|refer to)\s+)?[^:;.!?]+\?"
    r"(?:\s*or\s+[^:;.!?]+\?)?"
    r"|(?:請|请)?(?:解釋|解释|說明|说明)(?:上面|上述|前述)"
    r"(?:引用證據|引用证据|引用|證據|证据)(?:中|的)?"
    r"[^:;.!?。；！？]+(?:代表什麼|代表什么|意思|含義|含义)[。.!?]?"
    r"|(?:這|这|該|该)(?:個|个|項|项)?(?:日期|時間|时间|數值|数值|欄位|字段|標籤|标签)"
    r"(?:是|代表|表示)[^:;.!?。；！？]+\?"
    r"(?:\s*(?:還是|还是)[^:;.!?。；！？]+\?)?"
)
# A second instruction outside supplied quotations must keep the evidence route.
_TEXT_TASK_ACTION = re.compile(
    r"(?:(?<![a-z0-9_])(?:find|search|check|retrieve|look up|show|get|"
    r"tell|confirm|return|list|what|which|who)\b|"
    r"查|找|搜尋|搜索|確認|列出|調閱|告訴)"
)
_ADDITIONAL_TEXT_TASK_ACTION = re.compile(
    r"(?:[,.;!?，。；！？]\s*|\b(?:and|also|then)\s+|(?:並|另|再)(?:請)?)"
    r"(?:please\s+|請|请)?(?:also\s+|then\s+)?"
    + _TEXT_TASK_ACTION.pattern
)
_TEXT_TASK_SOURCE_BINDING = re.compile(
    r"\b(?:using|from|based on|according to)\b[^.!?;]*"
    r"\b(?:records?|evidence|mail|email|inbox|documents?|reports?|files?|attachments?)\b"
    r"|(?:根據|依据|依據|使用|參考)[^。；！？]*(?:資料|紀錄|記錄|郵件|文件|報告|附件)"
)
_TEXT_ONLY_CONSTRAINT_TAIL = re.compile(
    r"(?:[,;]\s*(?:也)?(?:不用|不要|不需|請勿|不)"
    r"(?:(?:查(?:詢|找)?|搜尋|搜索)(?:(?:公司|內部|工作區)?資料)?(?:或寄信)?"
    r"|(?:填入?|填寫)(?:任何)?(?:真實|實際)[^,;.!?。]{0,32}(?:資料|資訊)))+[。.!?]?$"
)
_NEGATED_TEXT_LOOKUP_TAIL = re.compile(
    r"[,;.，；。]\s*(?:(?:please\s+)?(?:do not|don['’]t|no need to)\s+"
    r"(?:search|look up|check|retrieve|query)\b"
    r"|(?:請|请)?(?:也)?(?:不用|不需要|不需|不必|不要|請勿|请勿|不)(?:去)?"
    r"(?:查(?:詢|询|找)?|搜尋|搜索))"
    r'(?P<remainder>[^,:;，；.!?。！？"“”「」『』]*)[。.!?]?$'
)
_EXPLICIT_WORKSPACE_MARKERS = (
    "my mail",
    "my email",
    "my messages",
    "my inbox",
    "from my inbox",
    "workspace",
    "信箱",
    "我的信件",
    "我的郵件",
    "我的信箱",
    "工作區",
)
_MAIL_CONTENT_MARKERS = ("mail", "email", "message", "信件", "郵件", "信箱")
# A bare "信" is ambiguous (信心/信任/信號).  Require a mail noun construction:
# incoming/outgoing/received correspondence, a possessive, or the classifier 封.
# This also covers intervening recipients/modifiers through "的信" and "封信".
_CJK_MAIL_CONTENT_PATTERN = re.compile(
    r"(?:往[來来]的?|[來来]|(?:寄[出來来]|收[到取])的?|的|封)" r"信(?![心任念仰用號号息賴赖])"
)
_CJK_MAIL_REFERENCE_PATTERN = re.compile(r"的(?:信件|郵件|信箱)")
# A source-backed row lookup must not depend on a fixed business-field
# vocabulary.  UAT users can ask for an arbitrary column label (for example a
# tenant-specific field name), so an identifier followed by a record reference
# and 的 is a stronger routing signal than the known-field marker list.
_RECORD_FIELD_LOOKUP_PATTERN = re.compile(
    r"(?:\b[a-z0-9][a-z0-9._/-]{1,63}\b|[\u4e00-\u9fff]{2,24})"
    r"\s*(?:這|該|此)(?:筆|項|個)(?:資料|目|項目)?\s*的"
)
_EVIDENCE_RETURN_PATTERN = re.compile(
    r"^(?:please\s+)?return\b[^?]*\b"
    r"(?:rows?|records?|documents?|evidence|files?|messages?|values?|citations?)\b"
)
# Workspace evidence is not limited to mail.  Match source nouns with word
# boundaries in English; Chinese source nouns already form lexical units.
# A noun alone is not a lookup: the action check below is still required.
_WORKSPACE_CONTENT_PATTERN = re.compile(
    r"\b(?:projects?|documents?|files?|records?|attachments?|reports?|"
    r"issues?|tickets?|repositories|repository|evidence)\b"
    r"|專案|项目|項目|文件|文檔|文档|檔案|档案|資料|数据|紀錄|記錄|记录|"
    r"附件|報告|报告|工單|工单|證據|证据"
)
_BUSINESS_SOURCE_MARKERS = (
    "bom",
    "coo",
    "component",
    "components",
    "country of origin",
    "delivery",
    "eta",
    "etd",
    "inventory",
    "item",
    "items",
    "lead time",
    "lookup",
    "material",
    "materials",
    "mpn",
    "part",
    "parts",
    "po",
    "procurement",
    "product",
    "products",
    "purchase order",
    "quantity",
    "quote",
    "rfq",
    "row",
    "rows",
    "sku",
    "source",
    "stock",
    "supplier",
    "table",
    "vendor",
    "warehouse",
)
_BUSINESS_SOURCE_CJK_MARKERS = (
    "交期",
    "交貨",
    "供應鏈",
    "倉庫",
    "庫存",
    "存貨",
    "料件",
    "料號",
    "零件",
    "產品",
    "品項",
    "數量",
    "物料",
    "採購",
    "訂單",
    "報價",
    "產地",
    "出貨",
)
_EVIDENCE_QUERY_ACTION_MARKERS = (
    "find",
    "search",
    "list",
    "show",
    "retrieve",
    "organize",
    "summarize",
    "summarise",
    "review",
    "check",
    "get",
    "look up",
    "lookup",
    "read",
    "整理",
    "找",
    "查",
    "搜尋",
    "搜索",
    "列出",
    "列舉",
    "調閱",
    "查看",
    "查找",
    "盤點",
    "摘要",
    "總結",
    "看",
    "讀",
)
_BUSINESS_DEFINITION_MARKERS = (
    "what is",
    "what are",
    "define",
    "definition of",
    "meaning of",
    "how does",
    "how do",
    "什麼是",
    "什么是",
    "是什麼",
    "是什么",
    "何謂",
    "意思",
)
_BUSINESS_CURRENT_STATE_MARKERS = (
    "current",
    "latest",
    "status",
    "state",
    "due",
    "deadline",
    "today",
    "目前",
    "現在",
    "最新",
    "狀態",
    "状态",
    "進度",
    "进度",
)


def protected_reference_identifiers(text: str) -> tuple[str, ...]:
    """Reuse the frozen identifier policy; prose, dates and amounts are not anchors."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(sorted({span.exact_token for span in _protected_identifier_spans(normalized)
                         if span.identifier_kind == "business_identifier"}))


def has_explicit_record_target(text: str) -> bool:
    """Current protected IDs or structural numeric record/field bindings win.

    A number alone is not an anchor. Inspect closed clauses so a supplied scalar
    calculation beside an unresolved reference cannot become a record target.
    """
    normalized = _without_negative_retrieval_tail(_normalize_routing_text(text))
    if protected_reference_identifiers(normalized):
        return True
    # Retain terminators: the existing field-for-target grammar also uses '?'.
    for clause in re.split(r"(?<=[,;。!?！？])|(?<=\.)(?![0-9])", normalized):
        clause = re.sub(r"^(?:(?:and|but|also|then)\s+|再|並|并|另)", "", clause.strip())
        if clause and not _is_self_contained_text_task(clause.rstrip(",;")) and _has_identifier_field_request(clause):
            return True
    return False


def is_identifier_reference(text: str) -> bool:
    """Recognize a reference data request, not a bare pronoun or product mention."""
    text = _without_negative_retrieval_tail(_normalize_routing_text(text))
    if _is_self_contained_text_task(text):
        return False
    # Quoted examples are supplied text, not reference-question grammar.
    text = _identifier_request_instruction(text, drop_topics=True)
    text = _bounded_selection_view(text)[0]
    legacy_request_intent = any(
        re.search(rf"\b{re.escape(term)}\b", text) if term.isascii() else term in text
        for term in _EVIDENCE_QUERY_ACTION_MARKERS
    ) or re.search(r"\b(?:what|which|who|where|when)\b|什麼|什么|誰|谁|哪|(?:呢|嗎|吗)[?？]?$", text)
    # Only the newly admitted nonterminal particle questions need clause-local
    # referents: a greeting cannot borrow a product mention from another clause.
    clauses = (text,) if legacy_request_intent else re.findall(
        r"[^,;.!?。！？]*(?:呢|嗎|吗)[?？]", text,
    )
    return any(re.search(
        r"\b(?:this|that|same|previous)\s+(?:part|item|product|component|record|identifier|order)\b"
        r"|\b(?:its|their)\s+\w+|(?:這|这|那|該|该|此|上述|前述)(?:個|个|筆|笔|項|项)?"
        r"(?:料號|料号|零件|產品|产品|品項|品项|紀錄|记录|訂單|订单)|(?:它|其)的"
        # A prior-action relative clause is also a referent, not a new source
        # target. The runtime still requires its trusted, scoped binding.
        r"|(?:剛剛|剛才|刚刚|刚才|先前|之前|上次)(?:查(?:詢|询)?|提到|提及|討論|讨论)"
        r"(?:過|过)?的(?:(?:那|這|这)(?:個|个|筆|笔|項|项))?"
        r"(?:料號|料号|識別碼|识别码|零件|產品|产品|品項|品项|紀錄|记录|訂單|订单)"
        r"|\b(?:part|item|product|component|record|identifier|order)\s+"
        r"(?:that\s+)?(?:we|i|you)\s+(?:just|previously|earlier)\s+"
        r"(?:looked up|queried|searched|discussed|mentioned)\b"
        r"|\b(?:part|item|product|component|record|identifier|order)\s+did\s+"
        r"(?:we|i|you)\s+(?:just|previously|earlier)\s+"
        r"(?:look up|query|search|discuss|mention)\b",
        clause, re.IGNORECASE,
    ) for clause in clauses)


def is_prior_evidence_interpretation(query_text: str) -> bool:
    """Recognize an interpretation-only reference; callers must bind cited state.

    This does not resolve a date/number to an identifier or assert that a label
    is supported. The retained bundle must support it, otherwise clarify.
    """
    _require_nonempty_public_string(query_text, "query_text")
    normalized = _without_negative_retrieval_tail(_normalize_routing_text(query_text))
    if _PRIOR_INTERPRETATION.fullmatch(normalized) is None:
        return False
    return not (
        protected_reference_identifiers(normalized)
        or re.search(r"\d", normalized)
        or re.search(r"\b(?:all|every|complete|entire|none)\b|全部|所有|每(?:一|個|个|筆|笔|封|件)|完整", normalized)
        or _TEXT_TASK_SOURCE_BINDING.search(normalized)
        or any(
            re.search(rf"\b{re.escape(marker)}\b", normalized) if marker.isascii() else marker in normalized
            for marker in (*_EVIDENCE_QUERY_ACTION_MARKERS, *_BUSINESS_CURRENT_STATE_MARKERS,
                           *_EXPLICIT_WORKSPACE_MARKERS, "count", "how many", "多少", "總數", "總計", "合計")
        )
    )


def _is_retained_relative_presentation(
    normalized: str, *, require_citation_preservation: bool = False,
) -> bool:
    """Close an outer transform over prior retrieval, not a fresh query.

    The caller supplies both retained-state gates. Past retrieval in the
    relative clause is provenance; every additional clause must only preserve
    citations or prohibit another search. Unknown/mixed clauses fall through.
    """
    clauses = re.split(r"[,;。!?！？]", normalized.rstrip(".!?。！？"))
    preserve = (
        r"(?:keep|retain|preserve|reuse)\s+(?:the\s+)?"
        r"(?:(?:(?:original(?:\s+and\s+converted)?|converted)\s+)?(?:values|units)\s+and\s+)*"
        r"(?:the\s+)?(?:(?:same|original|prior|existing)\s+)?(?:citations|references)"
        r"|(?:保留|沿用|維持|维持)"
        r"(?:(?:原始|原有|原本|換算|换算|轉換|转换)?(?:數值|数值|值|單位|单位)[、和及與与])*"
        r"(?:原本|原有|先前|原來|原来|相同)?(?:的)?(?:引用|來源引用)"
    )
    modifier = (
        preserve
        + r"|(?:do not|don't|no need to)\s+(?:search|retrieve|look up|query)(?:\s+(?:again|anew))?"
        r"|without\s+(?:a\s+)?(?:new\s+)?(?:search|lookup)"
        r"|(?:不用|不需要|不需|不必|不要|請勿|请勿)(?:重新|再次|再)?(?:搜尋|搜索|查詢|查询|查找)"
    )
    if any(not re.fullmatch(modifier, clause.strip()) for clause in clauses[1:]):
        return False
    if require_citation_preservation and not any(
        re.fullmatch(preserve, clause.strip()) for clause in clauses[1:]
    ):
        return False
    label = r"(?P<label>[^,:;.!?。！？]{1,80}?)"
    match = re.fullmatch(
        r"(?:please\s+)?(?:translate|rewrite|reformat|summarize)\s+(?:the\s+)?" + label
        + r"\s+(?:that\s+)?(?:you|we)\s+(?:(?:previously|earlier|just)\s+)?"
        r"(?:found|retrieved|looked up|cited)(?:\s+(?:earlier|previously|above))?"
        r"(?:\s+(?:in|into|as)\s+(?:[a-z]{2,20}|a\s+(?:table|list|summary)))?",
        clauses[0].strip(),
    ) or re.fullmatch(
        r"(?:請|请)?(?:把|將|将)(?:你|您|我們|我们)"
        r"(?:先前|之前|剛才|刚才|上次|上一(?:則|则|次))"
        r"(?:(?:找到|查到|檢索到|检索到|引用)的|的)" + label
        + r"(?:翻(?:譯|译)?|改寫|改写|整理)(?:成|為|为)"
        r"(?:英文|中文|日文|法文|德文|西班牙文|表格|清單|列表)",
        clauses[0].strip(),
    )
    if match is None:
        return bool(_PRIOR_PRESENTATION.fullmatch(clauses[0].strip()) or re.fullmatch(
            r"(?:please\s+)?(?:translate|rewrite|reformat|summarize)\s+(?:the\s+|your\s+)?"
            r"(?:previous|prior|last|above)\s+(?:answer|response|result)"
            r"(?:\s+(?:in|into|as)\s+(?:[a-z]{2,20}|a\s+(?:table|list|summary)))?",
            clauses[0].strip(),
        ))
    subject = match["label"]
    return not (
        protected_reference_identifiers(subject)
        or _TEXT_TASK_ACTION.search(subject)
        or _TEXT_TASK_SOURCE_BINDING.search(subject)
        or _has_explicit_workspace_evidence_marker(subject)
        or re.search(r"[\"'“”「」『』]", subject)
    )


def _original_attachment_page(text: str):
    """Bind independent source/coordinate spans; target terms remain literal AND."""
    if _is_self_contained_text_task(text, require_supplied_input=True):
        return None, None
    quoted = r'(?:"[^"\n]{1,80}"|「[^「」\n]{1,80}」|“[^“”\n]{1,80}”)'
    quotes = list(re.finditer(quoted, text))
    instruction = re.sub(quoted, lambda m: " " * len(m[0]), text)
    sources = list(re.finditer(r"\battachments?\b|附件", instruction))
    if not sources:
        return None, None
    coordinate = r'(?:\bpages?\s+[+-]?[0-9]+(?:\.[0-9]+)?\b|第\s*[+-]?[0-9]+(?:\.[0-9]+)?(?:\s*[-至到]\s*[0-9]+)?\s*[頁页])'
    coordinates = [m for m in re.finditer(coordinate, instruction)
                   if not re.search(r'\bliteral\s*$', text[:m.start()])]
    if not coordinates:
        return None, None
    if len(coordinates) != 1 or len(sources) != 1:
        return None, "native_page_ambiguous"
    coord, source = coordinates[0], sources[0]
    numeric = re.fullmatch(r'(?:page\s+([0-9]+)|第\s*([0-9]+)\s*[頁页])', coord[0])
    if (numeric is None or source[0] == "attachments"
            or re.match(r'\s*(?:[-–—]|\.\d)', instruction[coord.end():])
            or re.search(r"\bdocuments?\b|文件", instruction)):
        return None, "native_page_ambiguous"
    # Negation belongs to its clause, not the whole question. Output constraints
    # in separate/conjoined clauses do not negate a positive source coordinate.
    boundary = r'[,;，；。.!?！？]|\b(?:and|but|then)\b|並|并|但|再'
    negative = r"\b(?:not|no|never|except|exclud\w*|outside|apart\s+from|other\s+than|instead|or|compare|between|through)\b|不|勿|非|排除|除|以外|之外|或者|比較|比较|至|到"
    for clause in re.finditer(r'.+?(?=' + boundary + r'|$)', instruction):
        if (any(clause.start() <= anchor.start() < clause.end() for anchor in (source, coord))
                and re.search(negative, clause[0])):
            return None, "native_page_ambiguous"
    page = int(numeric[1] or numeric[2])
    if page < 1:
        return None, "native_page_ambiguous"
    # Preserve explicit source titles when present, without requiring one or
    # coupling it to coordinate order. Other targets use the existing binder.
    titles = tuple(q[0][1:-1] for q in quotes if (
        q.start() >= source.end() and not text[source.end():q.start()].strip()
        or q.end() <= source.start() and not text[q.end():source.start()].strip()
    ))
    outside_coordinate = text[:coord.start()] + " " + text[coord.end():]
    targets = tuple(dict.fromkeys((*titles, *protected_reference_identifiers(outside_coordinate))))
    return ({"kind": "attachment_page", "page": page}, targets, coord[0]), None


def requires_workspace_evidence(
    query_text: str,
    *,
    query_class: str | None = None,
    prior_evidence_citeable: bool = False,
    prior_evidence_present: bool = False,
) -> bool:
    """Return whether the user explicitly requested governed workspace evidence.

    ``deterministic_query_class`` controls the claim and execution contract; it
    is deliberately not a tool-choice proxy.  Treating every classified query
    as a mandatory lookup turns ordinary conversation into an MCP request.
    """
    _require_nonempty_public_string(query_text, "query_text")
    normalized = _without_negative_retrieval_tail(_normalize_routing_text(query_text))
    if _is_self_contained_text_task(normalized):
        return False
    if prior_evidence_present and prior_evidence_citeable and (
        _PRIOR_PRESENTATION.fullmatch(normalized) or _is_retained_relative_presentation(normalized)
    ):
        return False
    if prior_evidence_present and prior_evidence_citeable and is_prior_evidence_interpretation(normalized):
        return False
    if _original_attachment_page(_normalize_routing_text(query_text))[0] is not None:
        return True
    if _has_source_quantified_operation(normalized) or _bounded_selection_view(normalized)[1]:
        return True
    if _has_identifier_field_request(normalized) or _has_identifier_event_request(normalized):
        return True
    # Operations over an unsupplied record property are not closed input.
    # Literal strings/lists/calculations already took the self-contained path.
    if protected_reference_identifiers(_identifier_request_instruction(normalized, drop_topics=True)) and (
        _TEXT_TASK_SOURCE_BINDING.search(normalized)
        or re.match(r"^(?:please\s+)?(?:repeat|count|calculate|compute|evaluate)\b", normalized)
    ):
        return True
    # Only identifiers in the current instruction admit this citation-request
    # gate. Quoted examples are not targets; the original tool query is intact.
    quoted_text = r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|(?<!\w)\x27[^\x27]*\x27(?!\w)'
    instruction = re.sub(quoted_text, " ", normalized)
    if protected_reference_identifiers(instruction) and (
        _CITATION_PRESENTATION_SUFFIX.search(instruction)
        or _EXPLICIT_CITATION_REQUEST_SUFFIX.search(instruction)
    ):
        return True
    # Quoted topics are not lookup instructions. Retain quoted lookup objects
    # when the surrounding request supplies an action, binding or current state.
    if not (
        protected_reference_identifiers(normalized)
        or _TEXT_TASK_SOURCE_BINDING.search(normalized)
        or any(
            # A target outside the quote still binds its quoted property.
            # A target mentioned only inside a quoted topic does not.
            re.search(r"(?:的|之)\s*$", normalized[:quoted.start()])
            and _has_scoped_business_source_signal(normalized[:quoted.start()] + quoted[0][1:-1])
            for quoted in re.finditer(quoted_text, normalized)
        )
        or any(
            re.search(rf"\b{re.escape(marker)}\b", instruction) if marker.isascii() else marker in instruction
            for marker in (*_EVIDENCE_QUERY_ACTION_MARKERS, *_BUSINESS_CURRENT_STATE_MARKERS)
        )
    ):
        normalized = instruction
    if _TEXT_TASK_SOURCE_BINDING.search(normalized) and re.match(
        r"^(?:please\s+)?(?:translate|rewrite|rephrase|proofread|summarize|draft|write|create|explain|describe|sort|reorder|reverse|count|deduplicate)\b"
        r"|^(?:請|请)?(?:根據|依據|依据|使用|參考|翻譯|翻译|改寫|改写|寫|撰寫|解釋|說明)",
        normalized,
    ):
        return True
    if _ADDITIONAL_TEXT_TASK_ACTION.search(normalized) and (protected_reference_identifiers(normalized) or any(
        re.search(rf"\b{re.escape(marker)}\b", normalized) if marker.isascii() else marker in normalized
        for marker in (*_BUSINESS_SOURCE_MARKERS, *_BUSINESS_SOURCE_CJK_MARKERS)
    )):
        return True
    # Prior misses do not authorize tools for ordinary chat. Current data
    # requests still require evidence; unresolved references are bound/clarified.
    return is_identifier_reference(normalized) or _has_explicit_workspace_evidence_marker(
        normalized
    ) or _has_business_source_signal(normalized)


def _identifier_request_instruction(normalized: str, *, drop_topics: bool = False) -> str:
    """Keep quoted target IDs, not identifiers inside quoted topics/examples."""
    quoted = r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|(?<!\w)\x27[^\x27]*\x27(?!\w)'
    def target_quote(match: re.Match[str]) -> str:
        content = match[0][1:-1].strip()
        identifiers = protected_reference_identifiers(content)
        # A quote containing an instruction/example is not a current target.
        return content if identifiers == (content,) else (
            ";" if identifiers or drop_topics else match[0]
        )
    return re.sub(quoted, target_quote, normalized)


def _has_identifier_event_request(normalized: str) -> bool:
    """Recognize factual propositions without a business-field/event vocabulary.

    This only admits planning; it cannot bind a value, grant scope or alter the
    protected-ID policy. Numeric targets need a separate type label, not just
    an operand, date or bare number. Inspect clauses independently so a supplied
    transformation cannot hide a later factual question.
    """
    # Quoted non-ID text is a topic or supplied value, never question grammar.
    instruction = _identifier_request_instruction(normalized, drop_topics=True)
    for clause in re.split(r"[,;。!?]|(?<![a-z0-9])\.|\.(?![a-z0-9])", instruction):
        clause = re.sub(r"^(?:(?:and|also|then)\s+|再|並|并|另)", "", clause.strip())
        # A polite ability wrapper asks us to perform the following task; it
        # does not make a supplied translation or joke a record proposition.
        clause = re.sub(r"^(?:can|could|would|will)\s+you\s+(?:please\s+)?", "", clause)
        clause = re.sub(r"^(?:please\s+)?(?:tell|show)\s+(?:me|us)\s+", "", clause)
        targets = set(protected_reference_identifiers(clause))
        # Literal arithmetic/comparison operands are supplied values, whatever noun
        # precedes them. Exclude spans, not the clause: another record target
        # (including a numeric one) must still authorize its factual request.
        scalar = r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
        operand = rf"\(*\s*{scalar}\s*\)*"
        operator = r"(?:\*\*|[+*/×÷^−-]|\b(?:plus|minus|times|divided by|multiplied by)\b|加|減|减|乘|除)"
        comparison = r"(?:[=<>≤≥≠]+|(?:is\s+)?(?:equal to|equals|greater than|less than)|(?:是否)?(?:等於|等于|大於|大于|小於|小于))"
        expressions = tuple(re.finditer(
            rf"(?<![a-z0-9._/-]){operand}(?:\s*(?:{operator}|{comparison})\s*{operand})+"
            rf"(?![a-z0-9._/-])", clause,
        ))
        # A type label is structural, not an allowlist of business domains.
        # Require a noun position, not the operator in 'does 12 divide 36'.
        for number in re.finditer(r"(?<![a-z0-9._/-])[0-9]+(?![a-z0-9._/-])", clause):
            if any(expr.start() <= number.start() and number.end() <= expr.end() for expr in expressions):
                continue
            # A calendar month followed by a year supplies temporal context,
            # not a record type and ID. Exempt only this occurrence: the same
            # digits may still identify an independently typed record below.
            if len(number[0]) == 4 and re.search(
                r"\b(?:january|february|march|april|may|june|july|august|"
                r"september|october|november|december)\s+$", clause[:number.start()],
            ):
                continue
            label = re.search(
                r"(?:\b(?:has|have|had|is|are|was|were|do|does|did|can|could|will|would|"
                r"should|may|might|must|to|for|on|of|in|from)\s+|^)(?:the\s+)?"
                r"((?:[a-z]+\s+){0,2}[a-z]+)\s+$"
                r"|([\u4e00-\u9fff]+)\s+$", clause[:number.start()],
            )
            # Compound record types are noun positions, not field synonyms.
            # Reject operator/scalar words anywhere in the bounded label so
            # a longer phrase cannot hide one of the existing exclusions.
            if label and not any(re.fullmatch(
                r"is|are|was|were|has|have|had|do|does|did|can|could|will|would|should|"
                r"may|might|must|of|for|to|in|on|at|since|before|after|than|by|and|or|"
                r"plus|minus|times|over|number|integer|scalar|numeral|數字|数字|是|在|於|于",
                word,
            ) for word in (label[1] or label[2]).split()):
                targets.add(number[0])
        if not targets:
            continue
        target_pattern = r"(?<![a-z0-9._/-])(?:" + "|".join(
            re.escape(target) for target in sorted(targets, key=len, reverse=True)
        ) + r")(?![a-z0-9._/-])"
        proposition = re.sub(target_pattern, " TARGET ", clause)
        # No predicate/business fact follows a bare identifier mention.
        if re.fullmatch(r"\s*TARGET\s*", proposition):
            continue
        if re.search(
            r"^(?:please\s+)?(?:(?:has|have|had|is|are|was|were|do|does|did|can|could|"
            r"will|would|should|may|might|must)\b|(?:what|which|who|where|when|why|how)\b"
            r"|(?:confirm|verify|determine|check)\s+(?:whether|if)\b)", proposition,
        ) or re.search(r"是否|有沒有|有没有|(?:嗎|吗|呢)\s*$", proposition):
            return True
        # Declarative question order: target + arbitrary predicate + '?'.
        if re.match(r"\s*TARGET\s+\S", proposition) and re.search(
            re.escape(clause) + r"\s*\?", instruction,
        ):
            return True
    return False


def _has_identifier_field_request(normalized: str) -> bool:
    """Bind arbitrary output fields to explicit targets, not a field-name list."""
    instruction = _identifier_request_instruction(normalized)
    targets = set(protected_reference_identifiers(instruction))
    # Numeric subjects also require a source-bound plan when used as record
    # targets; no requested-field vocabulary admits or rejects the request.
    # Pure scalar calculations are excluded by the supplied-task grammar first.
    for number in re.finditer(r"(?<![a-z0-9._-])[0-9]+(?![a-z0-9._-])", instruction):
        if not re.search(r"[0-9)]\s*[+*/×÷-]\s*$", instruction[:number.start()]):
            targets.add(number[0])
    for target in targets:
        identifier = rf"(?<![a-z0-9._-]){re.escape(target)}(?![a-z0-9._-])"
        if re.search(identifier + r"\s*(?:(?:這|这|該|该|此)?(?:列|行|筆|笔|紀錄|记录))?"
                     r"\s*(?:的|之|['’]s)\s*[^,;.!?。！？\s]+", instruction):
            return True
        if re.search(r"\b(?:of|for)\s+(?:(?:the|order|record|item|row|entry)\s+)?" + identifier, instruction) and (
            re.search(r"\b(?:what|which|when|where|who|how)\b", instruction)
            or instruction.rstrip().endswith("?")
        ):
            return True
    return False


def requires_query_expansion(query_text: str) -> bool:
    """Return whether a terse evidence request needs a typed provider plan."""

    _require_nonempty_public_string(query_text, "query_text")
    normalized = _without_negative_retrieval_tail(_normalize_routing_text(query_text))
    if not requires_workspace_evidence(normalized):
        return False
    if _EVIDENCE_RETURN_PATTERN.search(normalized) is not None:
        return False
    if any(marker in normalized for marker in _EVIDENCE_QUERY_ACTION_MARKERS):
        return False
    if any(marker in normalized for marker in _BUSINESS_CURRENT_STATE_MARKERS):
        return False
    if any(marker in normalized for marker in _MAIL_CONTENT_MARKERS):
        return False
    return any(
        marker in normalized
        for marker in (*_BUSINESS_SOURCE_CJK_MARKERS, *_BUSINESS_SOURCE_MARKERS, *_RELATION_TERMS)
    )


def is_ordinary_greeting(query_text: str) -> bool:
    """Return whether a turn is a plain greeting, without classifying its topic."""

    _require_nonempty_public_string(query_text, "query_text")
    return _is_ordinary_greeting(_normalize_routing_text(query_text))


def _normalize_routing_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _without_negative_retrieval_tail(normalized: str) -> str:
    """Remove closed negative constraints, not affirmative retrieval intent."""
    normalized = _TEXT_ONLY_CONSTRAINT_TAIL.sub("", normalized)
    while (tail := _NEGATED_TEXT_LOOKUP_TAIL.search(normalized)) is not None:
        # Negation covers one lookup clause, not a later positive action or
        # contrast. Ambiguous coordination stays on the governed route.
        if (
            re.search(r"\b(?:and|but|then|also|instead)\b|並|并|但|另|再|還|还", tail[0])
            or _TEXT_TASK_ACTION.search(tail["remainder"])
        ):
            break
        normalized = _TEXT_ONLY_CONSTRAINT_TAIL.sub("", normalized[:tail.start()])
    return normalized


def _without_closed_output_format_tail(normalized: str) -> str:
    """Remove only complete presentation clauses, never source/data operations."""
    pattern = rf"(?P<separator>[,;.!?。！？])\s*(?:{_TEXT_OUTPUT_FORMAT_CLAUSE})[.!?。！？]*\s*$"
    while (tail := re.search(pattern, normalized)) is not None:
        separator = tail["separator"]
        # Retain question/sentence punctuation used by the original task shape.
        normalized = normalized[:tail.start()] + (separator if separator not in ",;" else "")
    return normalized


def _without_closed_task_constraints(normalized: str, *, list_policy: bool = False) -> str:
    """Consume whole constraint clauses, never arbitrary residual instructions."""
    while True:
        stripped = _without_closed_output_format_tail(_without_negative_retrieval_tail(normalized))
        if list_policy:
            stripped = re.sub(
                rf"[,;.。]\s*(?:{_LIST_COUNT_POLICY_CLAUSE})[ .!?。！？]*$", "", stripped,
            )
        if stripped == normalized:
            return normalized
        normalized = stripped


def _is_closed_supplied_operation(normalized: str) -> bool:
    """Read literal operands, never resolve record values or compute an answer."""
    operand = rf"(?:\(\s*{_LITERAL_SCALAR}\s*\)|{_LITERAL_SCALAR})"
    # A supplied-input label can introduce scalars, but never supplies a value
    # itself. Every operand and the entire residual operation must still match.
    introduction = r"(?:(?:the\s+)?(?:supplied|provided|following)\s+(?:values?|numbers?)\s*:?\s*)?"
    operand = rf"{introduction}{operand}"
    operator = r"(?:\*\*|[+*/×÷^−-]|\b(?:plus|minus|times|divided by|multiplied by)\b)"
    if re.fullmatch(
        rf"(?:please\s+)?(?:add\s+{operand}(?:\s*,\s*{operand})*\s+(?:and|to)\s+{operand}"
        rf"|subtract\s+{operand}\s+from\s+{operand}"
        rf"|(?:multiply|divide)\s+{operand}\s+by\s+{operand}"
        rf"|(?:calculate|compute|evaluate)\s+{operand}(?:\s*{operator}\s*{operand})+)"
        r"[ .!?。！？]*", normalized,
    ):
        return True
    quoted = r'"[^"\n]+"|“[^”\n]+”|「[^」\n]+」|『[^』\n]+』|\x27[^\x27\n]+\x27'
    value = rf"(?:{quoted}|[^\s,;:。!?]+)"
    if re.fullmatch(
        rf"(?:(?:please\s+)?repeat\s+(?:(?:the\s+)?(?:supplied\s+)?string\s+)?{value}\s+"
        rf"(?:once|twice|(?:exactly\s+)?{_LITERAL_COUNT}\s+times)"
        rf"|(?:請|请)?(?:把|將|将)?(?:字串|字符串)\s*{value}\s*重複\s*{_LITERAL_COUNT}\s*次)[ .!?。！？]*",
        normalized,
    ):
        return True
    instruction, separator, data = normalized.partition(":")
    instruction = _without_negative_retrieval_tail(instruction).strip()
    # An explicit input-only calculation and fully literal numeric bindings.
    # Labels/units are opaque, not business-field dictionaries. Missing values
    # and extra instructions fail the whole shape instead of being discarded.
    if not separator or not re.fullmatch(
        r"(?:(?:請|请)?只使用(?:以下|下列|提供的)資料(?:計算|计算)?"
        r"|(?:please\s+)?(?:(?:calculate|compute|evaluate)\s+)?using\s+only\s+(?:the\s+)?"
        r"(?:following|supplied|provided)\s+data)", instruction,
    ):
        return False
    if protected_reference_identifiers(data) or _TEXT_TASK_SOURCE_BINDING.search(data):
        return False
    scalar = _LITERAL_SCALAR
    label = r"(?:[a-z]+(?:\s+[a-z]+){0,3}|[\u4e00-\u9fff]+)"
    binding = rf"{label}\s*(?:=|:)?\s*{scalar}(?:\s*(?:[a-z]+|[\u4e00-\u9fff]))?"
    # Only a closed output question follows the supplied assignments, not a
    # further data source, target or affirmative retrieval clause.
    return re.fullmatch(
        rf"\s*{binding}(?:\s*[,、;]\s*{binding})+\s*[,;.。]\s*"
        rf"(?:(?:{label}\s*(?:是)?多少|what\s+is\s+(?:the\s+)?{label})\s*[?？]"
        rf"|(?:請|请)?(?:計算|计算)\s*{label}"
        rf"|(?:please\s+)?(?:calculate|compute|evaluate)\s+(?:the\s+)?{label})[ .!。！]*",
        data,
    ) is not None


def _is_self_contained_text_task(normalized: str, *, require_supplied_input: bool = False) -> bool:
    """Recognize a bounded text task, never a general no-lookup override."""
    supplied_original = normalized
    # Constraints can alternate; consume only recognized closed suffixes.
    # The original request and any unresolved mixed clause remain untouched.
    normalized = _without_closed_task_constraints(normalized)
    # Literal scalar roots/powers supply their operands, not record targets.
    # Match the whole instruction: field names, unsupplied operands and later
    # lookup clauses cannot inherit this exemption. Never compute an answer.
    scalar = _LITERAL_SCALAR
    if re.fullmatch(
        rf"(?:(?:please\s+)?(?:(?:what is|what['’]s|calculate|compute|evaluate|find)\s+)?"
        rf"(?:(?:the\s+)?(?:(?:square|cube)(?:\s+root)?|[0-9]+(?:st|nd|rd|th)\s+root)"
        rf"\s+of\s+{scalar}|{scalar}\s+(?:squared|cubed|(?:raised\s+)?to\s+"
        rf"(?:the\s+)?power\s+(?:of\s+)?{scalar}))"
        rf"|(?:請|请)?(?:求|計算|计算)?\s*{scalar}\s*的\s*"
        rf"(?:(?:平方|立方)(?:根)?|{scalar}\s*次方)(?:是(?:多少|什麼|什么))?)"
        r"[ .!?。！？]*",
        normalized,
    ):
        return True
    # A closed, leading no-source constraint is not an affirmative lookup.
    # Still require the entire remaining instruction to be a supplied-text task;
    # mixed/contrasting source instructions cannot inherit this exemption.
    cjk_source = r"(?:(?:公司|內部|内部|工作區)?(?:資料庫|资料库|數據庫|数据库|資料|资料|來源|来源|文件|紀錄|記錄|记录|信件|郵件|邮件)|工作區|工作区)"
    en_source = r"(?:(?:(?:company|internal|workspace|my)\s+)?(?:data|sources?|records?|documents?|mail|email|inbox|databases?)|(?:the\s+)?workspace)"
    no_source = (
        r"(?:(?:請|请)?(?:不用|不需|不要|不必|不)(?:查(?:詢|询|找)?|搜尋|搜索)"
        rf"{cjk_source}(?:\s*(?:或|和|與|与|及|、)\s*{cjk_source})*"
        r"|(?:please\s+)?(?:do not|don['’]t|no need to)\s+"
        rf"(?:search|look up|check|retrieve|query)\s+{en_source}"
        rf"(?:(?:\s+(?:or|and)\s+|,\s*(?:(?:or|and)\s+)?){en_source})*)"
    )
    normalized = re.sub(rf"^{no_source}\s*[,;.。]\s*", "", normalized, count=1)
    # A negative source clause may sit between the supplied-text instruction and
    # its quoted input. Consume only whole known clauses outside that input;
    # all remaining exterior text must be closed transform instructions. Use
    # the original view so suffix stripping cannot hide a mixed source clause.
    quoted_input = re.search(r'"[^"]+"|“[^”]+”|「[^」]+」|『[^』]+』', supplied_original)
    if quoted_input is not None:
        exterior = (supplied_original[:quoted_input.start()].rstrip(": "),
                    supplied_original[quoted_input.end():])
        closed, removed = [], 0
        for part in exterior:
            remaining, count = re.subn(
                rf"(?:^|[,;.。])\s*{no_source}\s*(?=$|[,;.。])", "", part,
            )
            closed.append(remaining.strip(" ,:;.!?。！？"))
            removed += count
        if (removed and _TEXT_TASK_INSTRUCTION.fullmatch(closed[0])
                and (not closed[1] or _TEXT_TASK_INSTRUCTION.fullmatch(closed[1]))):
            return True
    if _is_closed_supplied_operation(normalized):
        return True
    # Only explicit operations over supplied input qualify. Formatting clauses
    # are closed grammar, not arbitrary prose that might contain another action.
    quote_pairs = {'"': '"', "'": "'", "“": "”", "「": "」", "『": "』"}
    quote = re.search('["“「『]', normalized)
    if quote is not None:
        instruction = _without_closed_task_constraints(normalized[:quote.start()].rstrip(": ")).strip()
        end = normalized.find(quote_pairs[quote[0]], quote.end())
        if end > quote.end() and re.fullmatch(
            r"(?:請|请)?(?:只|僅|仅)(?:根據|根据|依據|依据|使用)(?:這段|这段|以下|下列|提供的)"
            r"(?:文字|文本|內容|内容)(?:回答|作答)"
            r"|(?:please\s+)?answer\s+(?:using|based on)\s+only\s+(?:the\s+)?"
            r"(?:following|supplied|provided)\s+(?:text|passage)", instruction,
        ):
            supplied, question = normalized[quote.end():end], normalized[end + 1:].strip()
            # One question over this quoted input only. Unknown/new targets and
            # additional source operations cannot inherit the no-lookup clause.
            return bool(re.fullmatch(r'[^:;.!?"“”「」『』。！？]+\?', question)) and not (
                set(protected_reference_identifiers(question)) - set(protected_reference_identifiers(supplied))
                or _TEXT_TASK_SOURCE_BINDING.search(question)
                or _has_explicit_workspace_evidence_marker(question)
                or _has_source_quantified_operation(question)
                or any(re.search(rf"\b{re.escape(action)}\b", question) if action.isascii() else action in question
                       for action in _EVIDENCE_QUERY_ACTION_MARKERS)
            )
    list_instruction, list_separator, supplied_list = normalized.partition(":")
    list_instruction = _without_closed_task_constraints(list_instruction, list_policy=True)
    supplied_subject = (
        r"(?:下列|以下|這份|这份|提供的)(?:(?:[0-9]+|[零〇一二兩两三四五六七八九十百千萬万]+)(?:個|个|組|组|項|项))?"
        r"(?:單詞|单词|詞|词|數字|数字|值|文字|清單|清单|列表)"
    )
    supplied_operation = (
        r"(?:(?:依|按)(?:字母|數字|数字)(?:順序|顺序)?(?:排序|排列)|(?:倒序|逆序)?(?:排序|排列)"
        rf"|(?:翻譯|翻译)(?:成|為|为){_TEXT_TASK_CJK_LANGUAGE})"
    )
    if list_separator and re.fullmatch(
        rf"(?:(?:請|请)?(?:只)?(?:把|將|将)?{supplied_subject}{supplied_operation}"
        rf"|(?:請|请)?(?:只)?(?:把|將|将)?{supplied_subject}(?:整理|格式化)成(?:表格|清單|清单|列表)"
        r"|(?:please\s+)?(?:format|reformat)\s+(?:the\s+)?(?:following|supplied|provided)\s+"
        r"(?:text|data)\s+(?:as|into)\s+(?:a\s+)?(?:table|list)"
        rf"|(?:請|请)?(?:只)?(?:計算|计算|統計|统计|排序|去重){supplied_subject}(?:的(?:不同值|數量|数量|項目數|项目数))?"
        r"|(?:please\s+)?(?:count|sort|deduplicate)\b[^:;.!?]*\b(?:supplied|provided|following)\s+list(?:\s+only)?"
        r"|(?:please\s+)?(?:sort|reorder|reverse|deduplicate|count|translate)\s+(?:the\s+)?"
        r"(?:supplied|provided|following)\s+(?:list|words|values|items|numbers|text)"
        rf"(?:\s+(?:alphabetically|in\s+(?:ascending|descending|reverse)\s+order|into\s+{_TEXT_TASK_EN_LANGUAGE}))?)"
        rf"(?:[,;]\s*(?:{_TEXT_OUTPUT_FORMAT_CLAUSE}))*",
        list_instruction.strip(),
    ) and supplied_list.strip() and not _TEXT_TASK_SOURCE_BINDING.search(list_instruction):
        body = supplied_list.strip()
        # Duplicate inclusion/exclusion is an operation policy, not another
        # source request. Strip only the complete policy clause outside input.
        body = _without_closed_task_constraints(body, list_policy=True)
        if not body.strip():
            return False
        if body[0] in quote_pairs:
            # Source-looking text inside a whole quoted input is data; any
            # instruction after its closing quote remains outside the boundary.
            end = body.find(quote_pairs[body[0]], 1)
            return end > 1 and bool(re.fullmatch(r"[ .!?。！？]*", body[end + 1:]))
        return not (
            _TEXT_TASK_SOURCE_BINDING.search(body)
            or _has_identifier_field_request(body)
            or _has_identifier_event_request(body)
            or (protected_reference_identifiers(body) and (
                _CITATION_PRESENTATION_SUFFIX.search(body)
                or _EXPLICIT_CITATION_REQUEST_SUFFIX.search(body)
            ))
            or _TEXT_TASK_ACTION.match(body)
            or _ADDITIONAL_TEXT_TASK_ACTION.search(body)
        )
    quote = re.search('["“「『]', normalized)
    if quote is not None and re.fullmatch(
        r"(?:請|请)?(?:只)?(?:幫我|帮我)?(?:把|將|将)", normalized[:quote.start()].strip(),
    ):
        end = normalized.find(quote_pairs[quote[0]], quote.end())
        return end > quote.end() and bool(_TEXT_TASK_INSTRUCTION.fullmatch(
            normalized[end + 1:].strip().rstrip(" .!。！"),
        ))
    instruction, separator, supplied = normalized.partition(":")
    if not separator:
        quote = re.search('["“「『]', normalized)
        if quote is not None:
            instruction, supplied = normalized[:quote.start()], normalized[quote.start():]
    if supplied and _TEXT_TASK_INSTRUCTION.fullmatch(instruction.strip()):
        supplied = supplied.strip()
        if supplied[0] in quote_pairs:
            # Require the quote to consume the whole body; an outer lookup
            # clause cannot inherit the transformation's exemption.
            closing = quote_pairs[supplied[0]]
            end = supplied.find(closing, 1)
            return end > 1 and bool(re.fullmatch(
                rf"(?:(?:成|為|为)(?:自然|流暢|流畅)?{_TEXT_TASK_CJK_LANGUAGE})?[ .!。！]*",
                supplied[end + 1:],
            ))
        return (
            _NEGATED_TEXT_LOOKUP_TAIL.search(supplied) is None
            and _ADDITIONAL_TEXT_TASK_ACTION.search(supplied) is None
            and not _has_identifier_event_request(supplied)
        )

    # Context isolation needs an input-bearing branch above, not merely a
    # no-lookup explanation (which may interpret a retained cited value).
    if require_supplied_input:
        return False
    # Templates and explanations need an explicit generic framing. Concrete
    # subjects, source bindings and current values still require governance.
    generic = re.fullmatch(
        r"(?:please\s+)?(?:draft|write|create)\s+(?:a\s+)?(?:generic|blank|sample)\s+"
        r"[^:;.!?]+\btemplate\b[^:;.!?]*[.!]?"
        r"|(?:請|请)?(?:只)?(?:幫我|帮我)?(?:寫|撰寫)(?:一份|一封)?"
        r"[^:;。！？]+(?:範本|模板)[。]?"
        r"|(?:please\s+)?(?:explain|describe)\s+in general\s+[^:;.!?]+[.!?]?"
        r"|(?:please\s+)?(?:explain|describe)\s+(?:the\s+)?"
        r"(?:concept of|meaning of|difference between|relationship between|principles of)\s+[^:;.!?]+[.!?]?"
        r"|(?:please\s+)?explain\s+how\s+[^:;.!?]+\b(?:works?|affects?|relates? to)\b[^:;.!?]*[.!?]?"
        r"|(?:請)?一般性(?:解釋|說明)[^:;。！？]+[。]?"
        r"|(?:請)?(?:解釋|說明)[^:;。！？]+(?:概念|原理|定義|關係|差異|影響)[。]?"
        r"|一般(?:來說|来说|而言),[^:;.!?。]+(?:有什麼不同|有何不同)\?"
        r"\s*(?:請)?(?:解釋|說明)(?:概念|原理)[。]?",
        normalized,
    )
    return bool(generic) and not (
        # A retained negative tail has unresolved action scope, not a text-only exemption.
        _NEGATED_TEXT_LOOKUP_TAIL.search(normalized)
        or _has_scoped_business_source_signal(normalized)
        or protected_reference_identifiers(normalized)
        or any(marker in normalized for marker in _EXPLICIT_WORKSPACE_MARKERS)
        or any(marker in normalized for marker in _BUSINESS_CURRENT_STATE_MARKERS)
        or re.search(r"\b(?:my|our|this|that|its|their)\b|我們|我们|我的|它的|其的", normalized)
        or re.search(r"\b[a-z]+['’]s\b", normalized)
        or re.search(r"\b(?:using|from|based on|according to)\b|根據|依据|依據|使用|參考", normalized)
        or _ADDITIONAL_TEXT_TASK_ACTION.search(normalized)
    )


def _is_ordinary_greeting(normalized: str) -> bool:
    # Greeting prefixes are ordinary conversation unless the explicit-source
    # check above has already found a workspace/mail task.  Do not maintain a
    # question-specific catalogue of acceptable greeting tails.
    return any(
        normalized == marker
        or normalized.startswith(f"{marker} ")
        or normalized.startswith(f"{marker},")
        or normalized.startswith(f"{marker}，")
        or normalized.startswith(f"{marker}!")
        or normalized.startswith(f"{marker}！")
        for marker in _GREETING_MARKERS
    )


def _has_explicit_workspace_evidence_marker(normalized: str) -> bool:
    if _EVIDENCE_RETURN_PATTERN.search(normalized) is not None:
        return True
    if any(marker in normalized for marker in _EXPLICIT_WORKSPACE_MARKERS):
        return True
    if _CJK_MAIL_REFERENCE_PATTERN.search(normalized) is not None:
        return True
    if _RECORD_FIELD_LOOKUP_PATTERN.search(normalized) is not None:
        return True
    if any(term in normalized for term in _RELATION_TERMS) and any(
        action_marker in normalized for action_marker in _EVIDENCE_QUERY_ACTION_MARKERS
    ):
        return True
    return (
        any(mail_marker in normalized for mail_marker in _MAIL_CONTENT_MARKERS)
        or _CJK_MAIL_CONTENT_PATTERN.search(normalized) is not None
        or _WORKSPACE_CONTENT_PATTERN.search(normalized) is not None
    ) and any(action_marker in normalized for action_marker in _EVIDENCE_QUERY_ACTION_MARKERS)


def _has_source_quantified_operation(normalized: str) -> bool:
    """Require exact operation + source operand in an outer instruction clause."""
    quoted = r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|(?<!\w)\x27[^\x27]*\x27(?!\w)'
    # Keep offsets: supplied quotations cannot supply operations or source nouns.
    instruction = re.sub(quoted, lambda match: " " * len(match[0]), normalized)
    mail = "|".join(re.escape(word) + (r"s?\b" if word.isascii() else "")
                    for word in _MAIL_CONTENT_MARKERS)
    source = rf"(?:{_WORKSPACE_CONTENT_PATTERN.pattern}|{mail})"
    noun = rf"{source}(?:\s+{source})?"
    determiner = r"(?:(?:the|all|every|each|available|authorized)\s+)*"
    english = re.compile(
        rf"^(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
        rf"(?:count\s+{determiner}(?:number\s+of\s+)?{noun}"
        rf"|how\s+many\s+{determiner}{noun})"
        r"(?:\s+(?:are|is)(?:\s+there)?(?:\s+available)?|\s+exist)?$",
    )
    quantity = rf"(?:(?:總共|总共)?有|共有)?(?:幾|几)[{_CJK_RECORD_CLASSIFIERS}]?"
    cjk = re.compile(
        rf"^(?:請|请)?(?:(?:計算|计算|統計|统计)(?:全部|所有|每)?{source}"
        rf"|{source}(?:{quantity}|(?:有)?多少)"
        rf"|{quantity}{source})$",
    )
    def direct(clause: str) -> bool:
        clause = re.sub(r"^(?:(?:and|then|also|but)\s+|再|並|并|另)", "", clause.strip())
        return bool((english.fullmatch(clause) or cjk.fullmatch(clause))
                    and deterministic_query_class(clause) == "exact_set_or_inventory")

    for span in re.finditer(r"[^,;.!?。！？]+", instruction):
        clause = span[0].strip()
        if direct(clause):
            return True
        # A joined outer operation may follow a complete supplied transform.
        # Do not split procedural explanations into fictitious instructions.
        for join in re.finditer(r"\b(?:and|then|also)\s+|並|并|再", span[0]):
            prefix = normalized[span.start():span.start() + join.start()].strip()
            if (_is_self_contained_text_task(prefix)
                    and direct(span[0][join.end():])):
                return True
    return False


def _has_business_source_signal(normalized: str) -> bool:
    if any(marker in normalized for marker in _BUSINESS_DEFINITION_MARKERS):
        # A definition request is ordinary conversation unless it also asks
        # for a current/source-backed business value.  A property attached to
        # a concrete subject is also source-backed: e.g. ``X 的 COO`` asks for
        # the value of COO for X, while ``What is a supplier?`` remains chat.
        if (
            not any(marker in normalized for marker in _BUSINESS_CURRENT_STATE_MARKERS)
            and not _has_scoped_business_source_signal(normalized)
        ):
            return False
    if _has_scoped_business_source_signal(normalized):
        return True
    cjk_markers = tuple(marker for marker in _BUSINESS_SOURCE_CJK_MARKERS if marker in normalized)
    if cjk_markers:
        # Preserve terse subject+field requests, not arbitrary sentences that
        # merely mention a business noun. The existing field vocabulary stays fixed.
        if any(re.fullmatch(
            rf"(?:[\u4e00-\u9fff]{{2,32}}|[a-z0-9][a-z0-9._/-]{{1,63}})\s*"
            rf"{re.escape(marker)}\s*[.!?。！？]?", normalized,
        ) for marker in cjk_markers):
            return True
        # A greeting's question mark cannot lend intent to a separate mention.
        for clause in re.split(r"(?<=[,;.!?。！？])", normalized):
            if any(marker in clause for marker in cjk_markers) and (
                _TEXT_TASK_ACTION.search(clause)
                or re.search(r"什麼|什么|誰|谁|哪|多少|(?:呢|嗎|吗)[?？]?$|[?？]$", clause.strip())
            ):
                return True
    has_business_marker = bool(cjk_markers) or any(
        re.search(rf"\b{re.escape(marker)}\b", normalized) is not None
        for marker in _BUSINESS_SOURCE_MARKERS
    )
    if not has_business_marker:
        return False
    return (
        any(marker in normalized for marker in _EVIDENCE_QUERY_ACTION_MARKERS)
        or any(marker in normalized for marker in _BUSINESS_CURRENT_STATE_MARKERS)
    )


def _has_scoped_business_source_signal(normalized: str) -> bool:
    """Recognize a business field bound to a user-supplied subject.

    This is intentionally structural rather than a list of identifiers.  It
    lets a private entity or arbitrary source identifier make ``X 的 COO`` a
    governed lookup without turning bare acronym/field definitions into MCP
    calls.
    """

    # Generic English nouns are not source identifiers.  Keep identifier-bound
    # COO/field lookups while leaving definition questions in ordinary chat.
    english_subject = r"(?:[a-z0-9]*\d[a-z0-9._/-]*|[a-z0-9]+(?:[._/-][a-z0-9]+)+)"
    subject = rf"(?:{english_subject}|[\u4e00-\u9fff]{{2,32}})"
    for marker in (*_BUSINESS_SOURCE_CJK_MARKERS, *_BUSINESS_SOURCE_MARKERS):
        escaped_marker = re.escape(marker)
        if re.search(
            rf"{subject}\s*(?:的|之)\s*"
            # A known source property can follow another requested field.
            rf"(?:[^,:;.!?。；！？]{{1,32}}?(?:與|与|和|及|、)\s*)?"
            rf"{escaped_marker}(?![a-z0-9_])",
            normalized,
        ):
            return True
        if marker in _BUSINESS_SOURCE_MARKERS and re.search(
            rf"\b{escaped_marker}\b\s+(?:of|for)\s+{english_subject}",
            normalized,
        ):
            return True
    return False


_RELATION_TERMS = (
    "relation",
    "related",
    "relationship",
    "cross-message",
    "through",
    "關係",
    "關聯",
    "跨訊息",
    "透過",
)
_SUMMARY_TERMS = (
    "summarize",
    "summary",
    "overview",
    "總結",
    "摘要",
    "概況",
)


@dataclass(frozen=True)
class SemanticPlanLimits:
    max_hops: int = 2
    max_fanout: int = 8
    max_candidates: int = 24
    max_results: int = 64
    max_evidence: int = 96
    max_time_budget_ms: int = 2_000
    max_repairs: int = 1


DEFAULT_SEMANTIC_PLAN_LIMITS = SemanticPlanLimits()


@dataclass(frozen=True)
class AuthorizedSemanticSource:
    """One validated source-kind set and authorization-scope binding.

    ``source_kind`` remains the legacy native kind for existing single-family
    sources. The explicit multisource kind is only used when one revision
    contains both mail and independently registered text Observations.
    """

    source_kind: str
    workspace_id: str
    source_scope_ids: tuple[str, ...]
    authorized_permission_scopes: tuple[PermissionScope, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty_public_string(self.source_kind, "source_kind")
        if self.source_kind not in _SOURCE_OCCURRENCE_SCHEMA_BY_KIND:
            raise ContractValidationError("semantic query source kind is unsupported")
        _require_nonempty_public_string(self.workspace_id, "workspace_id")
        if not self.source_scope_ids or self.source_scope_ids != tuple(
            sorted(set(self.source_scope_ids))
        ):
            raise ContractValidationError("semantic query source scope is invalid")
        for source_scope_id in self.source_scope_ids:
            _require_nonempty_public_string(source_scope_id, "source_scope_id")
        if not isinstance(self.authorized_permission_scopes, tuple):
            raise ContractValidationError("semantic query permission scope binding is invalid")
        normalized_scopes: list[tuple[str, PermissionScope]] = []
        scope_ids: set[str] = set()
        for permission_scope in self.authorized_permission_scopes:
            normalized = _canonical_permission_scope(permission_scope)
            scope_id = normalized["scope_id"]
            assert isinstance(scope_id, str)
            if scope_id not in self.source_scope_ids or scope_id in scope_ids:
                raise ContractValidationError(
                    "semantic query permission scope binding is invalid"
                )
            scope_ids.add(scope_id)
            normalized_scopes.append((sha256_json(normalized), permission_scope))
        if tuple(hash_value for hash_value, _scope in normalized_scopes) != tuple(
            sorted(hash_value for hash_value, _scope in normalized_scopes)
        ):
            raise ContractValidationError(
                "semantic query permission scope binding is not canonical"
            )

    @property
    def occurrence_schema_id(self) -> str:
        return _SOURCE_OCCURRENCE_SCHEMA_BY_KIND[self.source_kind]

    @property
    def authorized_source_kinds(self) -> tuple[str, ...]:
        return _SOURCE_KIND_MEMBERS_BY_KIND[self.source_kind]

    def authorizes_source_kind(self, source_kind: str) -> bool:
        return source_kind in self.authorized_source_kinds

    @property
    def authorization_fingerprint(self) -> str:
        payload = {
            "schema_version": 1,
            "source_kind": self.source_kind,
            "occurrence_schema_id": self.occurrence_schema_id,
            "workspace_id": self.workspace_id,
            "source_scope_ids": list(self.source_scope_ids),
        }
        if self.authorized_permission_scopes:
            payload["authorized_permission_scope_hashes"] = [
                sha256_json(scope.to_dict())
                for scope in self.authorized_permission_scopes
            ]
        return sha256_json(payload)


def validated_authorized_semantic_source(
    *,
    source_kind: str,
    workspace_id: str,
    source_scope_ids: Sequence[str],
    authorized_permission_scopes: Sequence[PermissionScope] = (),
) -> AuthorizedSemanticSource:
    """Validate one upstream-authorized source scope without accepting mixed kinds."""

    normalized_scopes = tuple(
        sorted(
            authorized_permission_scopes,
            key=lambda scope: sha256_json(_canonical_permission_scope(scope)),
        )
    )
    return AuthorizedSemanticSource(
        source_kind=source_kind,
        workspace_id=workspace_id,
        source_scope_ids=tuple(sorted(set(source_scope_ids))),
        authorized_permission_scopes=normalized_scopes,
    )


def authorized_permission_scope_matches(
    permission_scope: Any,
    *,
    authorized_source: AuthorizedSemanticSource,
    source_kind: str | None = None,
) -> bool:
    """Check one native source permission without widening legacy bindings."""

    normalized = to_plain(permission_scope)
    if not isinstance(normalized, dict):
        return False
    scope_type = normalized.get("scope_type")
    scope_id = normalized.get("scope_id")
    if not isinstance(scope_type, str) or not isinstance(scope_id, str) or not scope_id:
        return False
    if source_kind is not None:
        if not authorized_source.authorizes_source_kind(source_kind):
            return False
        source_kinds = (source_kind,)
    else:
        source_kinds = authorized_source.authorized_source_kinds

    if GITHUB_PROJECT_OBSERVATION_SOURCE_KIND in source_kinds and (
        scope_type == "project" and scope_id in authorized_source.source_scope_ids
    ):
        return True
    if AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND in source_kinds:
        if scope_type == "workspace" and scope_id == authorized_source.workspace_id:
            return True
        if (
            scope_type == "mail_import_session"
            and scope_id in authorized_source.source_scope_ids
        ):
            return True
    if (
        AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND in source_kinds
        and scope_type == "workspace"
        and scope_id == authorized_source.workspace_id
        and scope_id in authorized_source.source_scope_ids
    ):
        return any(
            scope.to_dict() == normalized
            for scope in authorized_source.authorized_permission_scopes
        )
    if scope_type != "project" or scope_id not in authorized_source.source_scope_ids:
        return False
    return any(
        scope.to_dict() == normalized
        for scope in authorized_source.authorized_permission_scopes
    )


@dataclass(frozen=True)
class SemanticQueryPlan:
    """A revision-pinned plan whose scope can only be narrowed during repair."""

    query_hash: str
    query_class: str
    source_kind: str
    source_scope_ids: tuple[str, ...]
    workspace_id: str
    requester_user_id: str
    required_permissions: tuple[str, ...]
    user_graph_revision_id: str
    canonical_graph_revision_id: str
    ontology_revision_id: str
    assembly_policy_id: str
    allowed_paths: tuple[tuple[str, str], ...]
    seed_node_ids: tuple[str, ...]
    max_hops: int
    max_fanout: int
    candidate_limit: int
    result_limit: int
    evidence_budget: int
    time_budget_ms: int
    repair_budget: int
    repair_attempt_count: int
    claim_strength: str
    exact_operation: str | None = None
    exact_inventory_kind: str | None = None
    exact_filter_term_hashes: tuple[str, ...] = ()
    exact_projection_term_hashes: tuple[str, ...] = ()
    exact_column_value_hash_pairs: tuple[tuple[str, str], ...] = ()
    exact_lexical_term_ledger: tuple[tuple[str, str, str, str], ...] = ()
    exact_grammar_term_ledger: tuple[tuple[str, str], ...] = ()
    exact_grammar_policy_fingerprint: str | None = None
    exact_source_occurrence_provider_fingerprint: str | None = None
    exact_identifier_term_hashes: tuple[str, ...] = ()
    exact_topic_term_hashes: tuple[str, ...] = ()
    exact_normalized_field: str | None = None
    exact_predicate: str | None = None
    exact_operator: str | None = None
    target_core_supertype_id: str | None = None
    include_superseded: bool = False
    relation_repair_identifier_term_hashes: tuple[str, ...] = ()
    relation_repair_concept_term_hashes: tuple[str, ...] = ()
    relation_repair_policy_fingerprint: str | None = None
    relation_repair_vocabulary_fingerprint: str | None = None

    @property
    def plan_fingerprint(self) -> str:
        return sha256_json(self._fingerprint_payload())

    def _fingerprint_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "query_hash": self.query_hash,
            "query_class": self.query_class,
            "source_kind": self.source_kind,
            "source_scope_ids": list(self.source_scope_ids),
            "workspace_id": self.workspace_id,
            "requester_user_id": self.requester_user_id,
            "required_permissions": list(self.required_permissions),
            "user_graph_revision_id": self.user_graph_revision_id,
            "canonical_graph_revision_id": self.canonical_graph_revision_id,
            "ontology_revision_id": self.ontology_revision_id,
            "assembly_policy_id": self.assembly_policy_id,
            "allowed_paths": [list(path) for path in self.allowed_paths],
            "seed_node_ids": list(self.seed_node_ids),
            "max_hops": self.max_hops,
            "max_fanout": self.max_fanout,
            "candidate_limit": self.candidate_limit,
            "result_limit": self.result_limit,
            "evidence_budget": self.evidence_budget,
            "time_budget_ms": self.time_budget_ms,
            "repair_budget": self.repair_budget,
            "repair_attempt_count": self.repair_attempt_count,
            "claim_strength": self.claim_strength,
            "exact_operation": self.exact_operation,
            "exact_inventory_kind": self.exact_inventory_kind,
            "exact_filter_term_hashes": list(self.exact_filter_term_hashes),
            "exact_identifier_term_hashes": list(self.exact_identifier_term_hashes),
            "exact_topic_term_hashes": list(self.exact_topic_term_hashes),
            "target_core_supertype_id": self.target_core_supertype_id,
            "include_superseded": self.include_superseded,
        }
        if self.exact_normalized_field is not None:
            payload["exact_source_occurrence"] = [
                self.exact_normalized_field,
                self.exact_predicate,
                self.exact_operator,
            ]
        if self.exact_projection_term_hashes:
            payload["exact_projection_term_hashes"] = list(
                self.exact_projection_term_hashes
            )
        if self.exact_lexical_term_ledger:
            payload["exact_structured_query_binding"] = {
                "column_value_hash_pairs": [
                    list(pair) for pair in self.exact_column_value_hash_pairs
                ],
                "lexical_term_ledger": [
                    list(binding) for binding in self.exact_lexical_term_ledger
                ],
                "grammar_term_ledger": [
                    list(binding) for binding in self.exact_grammar_term_ledger
                ],
                "grammar_policy_fingerprint": (
                    self.exact_grammar_policy_fingerprint
                ),
                "provider_fingerprint": (
                    self.exact_source_occurrence_provider_fingerprint
                ),
            }
        if self.relation_repair_policy_fingerprint is not None:
            payload["relation_repair"] = {
                "identifier_term_hashes": list(self.relation_repair_identifier_term_hashes),
                "concept_term_hashes": list(self.relation_repair_concept_term_hashes),
                "policy_fingerprint": self.relation_repair_policy_fingerprint,
                "vocabulary_fingerprint": (self.relation_repair_vocabulary_fingerprint),
            }
        return payload

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": "formowl_semantic_query_plan_v1",
            "query_hash": self.query_hash,
            "query_class": self.query_class,
            "plan_fingerprint": self.plan_fingerprint,
            "source_kind_hash": sha256_json(self.source_kind),
            "source_scope_hashes": [
                sha256_json(source_scope_id) for source_scope_id in self.source_scope_ids
            ],
            "workspace_hash": sha256_json(self.workspace_id),
            "requester_hash": sha256_json(self.requester_user_id),
            "permission_hashes": [
                sha256_json(permission) for permission in self.required_permissions
            ],
            "revision_hashes": {
                "user_graph": sha256_json(self.user_graph_revision_id),
                "canonical_graph": sha256_json(self.canonical_graph_revision_id),
                "ontology": sha256_json(self.ontology_revision_id),
                "assembly_policy": sha256_json(self.assembly_policy_id),
            },
            "allowed_path_hashes": [
                sha256_json({"relation_type": relation_type, "direction": direction})
                for relation_type, direction in self.allowed_paths
            ],
            "seed_node_hashes": [sha256_json(node_id) for node_id in self.seed_node_ids],
            "max_hops": self.max_hops,
            "max_fanout": self.max_fanout,
            "candidate_limit": self.candidate_limit,
            "result_limit": self.result_limit,
            "evidence_budget": self.evidence_budget,
            "time_budget_ms": self.time_budget_ms,
            "repair_budget": self.repair_budget,
            "repair_attempt_count": self.repair_attempt_count,
            "claim_strength": self.claim_strength,
            "exact_operation_hash": (
                sha256_json(self.exact_operation) if self.exact_operation else None
            ),
            "exact_inventory_kind_hash": (
                sha256_json(self.exact_inventory_kind) if self.exact_inventory_kind else None
            ),
            "exact_filter_term_hashes": list(self.exact_filter_term_hashes),
            **(
                {"exact_projection_term_hashes": list(self.exact_projection_term_hashes)}
                if self.exact_projection_term_hashes
                else {}
            ),
            **(
                {
                    "exact_structured_query_binding": {
                        "column_value_hash_pairs": [
                            list(pair)
                            for pair in self.exact_column_value_hash_pairs
                        ],
                        "lexical_term_ledger": [
                            list(binding)
                            for binding in self.exact_lexical_term_ledger
                        ],
                        "grammar_term_ledger": [
                            list(binding)
                            for binding in self.exact_grammar_term_ledger
                        ],
                        "grammar_policy_fingerprint": (
                            self.exact_grammar_policy_fingerprint
                        ),
                        "provider_fingerprint": (
                            self.exact_source_occurrence_provider_fingerprint
                        ),
                    }
                }
                if self.exact_lexical_term_ledger
                else {}
            ),
            "exact_identifier_term_hashes": list(self.exact_identifier_term_hashes),
            "exact_topic_term_hashes": list(self.exact_topic_term_hashes),
            "target_core_supertype_hash": (
                sha256_json(self.target_core_supertype_id)
                if self.target_core_supertype_id
                else None
            ),
            "include_superseded": self.include_superseded,
        }
        if self.relation_repair_policy_fingerprint is not None:
            payload["relation_repair"] = {
                "identifier_term_hashes": list(self.relation_repair_identifier_term_hashes),
                "concept_term_hashes": list(self.relation_repair_concept_term_hashes),
                "policy_fingerprint": self.relation_repair_policy_fingerprint,
                "vocabulary_fingerprint": (self.relation_repair_vocabulary_fingerprint),
            }
        assert_public_payload_safe(payload, "semantic_query_plan")
        return payload


def _bounded_selection_view(text: str) -> tuple[str, bool]:
    """Bind output-only anaphora to one positive bounded source selection.

    Mask only grammar in the classifier/reference view, never original fields,
    literal predicates, source obligations or independent exact operations.
    """
    quoted = r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|(?<!\w)\x27[^\x27]*\x27(?!\w)'
    outer = re.sub(quoted, lambda m: ' ' * len(m[0]), text)
    actions = '|'.join(
        rf'\b{re.escape(a)}\b' if a.isascii() else re.escape(a)
        for a in sorted((*_EVIDENCE_QUERY_ACTION_MARKERS, 'select', 'choose', '找出'), key=len, reverse=True)
    )
    # Selection stems/complements are local operators, not source/field aliases.
    actions += r'|[選选](?:出|取|用|擇|择)?|挑(?:[選选]|出|取)?'
    output = r'(?:provide|give|show|include|list|cite|附上|附引用|引用|提供|列出|標示|标示)'
    framing = r'\b(?:please|as|for)\b|請|请|作為|作为|以|[\s,，:：()（）]'
    connective = r'\s*(?:(?:(?:and|also|then|please)\s+|並|并|也|再|請|请|逐一|分[別别])\s*)*'
    boundary = rf'[;；。.!?！？]|[,，](?={connective}(?:{actions}|{output}|for\b|each\b|every\b|每))'
    cuts = [0, *(m.end() for m in re.finditer(boundary, outer)), len(outer)]
    clauses = [(a, outer[a:b].rstrip(',，;；。.!?！？')) for a, b in zip(cuts, cuts[1:])]
    count = rf'(?<!\w)(?:a few|some|{_LITERAL_COUNT})(?!\w)|(?:{_LITERAL_COUNT}|幾|几|一些|少數)[則则筆笔份封個个]'
    example = r'\b(?:representative|examples?|samples?)\b|代表(?:例|性)|範例|范例|例子'
    mail = '|'.join(rf'\b{m}s?\b' if m.isascii() else m for m in _MAIL_CONTENT_MARKERS)
    mail += '|' + _CJK_MAIL_CONTENT_PATTERN.pattern + '|邮件'
    sources = rf'{_WORKSPACE_CONTENT_PATTERN.pattern}|{mail}|\bmemos?\b|備忘錄|备忘录'
    generic = r'\brecords?\b|紀錄|記錄|记录'
    carriers = generic + r'|\b(?:evidence|data)\b|資料|数据'
    candidates = []
    for i, (_, clause) in enumerate(clauses):
        acts, counts, nouns = (list(re.finditer(pattern, clause)) for pattern in (actions, count, sources))
        intro = clauses[i - 1][1] if i and not re.sub(example + '|' + framing, '', clauses[i - 1][1]) else ''
        # A comma suffix not split as a known directive is not selection authority.
        if len(acts) != 1 or len(counts) != 1 or not nouns or not re.search(example, intro + clause) or re.search('[,，]', clause):
            continue
        if re.sub(example + '|' + framing, '', clause[:acts[0].start()]):
            continue  # Not an affirmative imperative (e.g. explain/do not select).
        # Negation must govern an action, quantity or example intent; 不同 is
        # merely a descriptor, not a negative selection instruction.
        if re.search(rf'(?:\b(?:not|no|never|without)\s+(?:as\s+)?|不(?:要|是)?|勿|別|别|非)(?:{actions}|{count}|{example})'
                     r'|\b(?:or|all|every|each|except|excluding)\b|或|所有|全部|每|以外|之外|除外', clause):
            continue
        if re.search(r'\b(?:from|since|dated|before|after|in|of)\s*$|第$', clause[:counts[0].start()]):
            continue
        if counts[0].start() > nouns[0].start() and not re.match(rf'\s*(?:{example})', clause[counts[0].end():]):
            continue
        kinds = {('mail' if re.fullmatch(mail, n[0]) else n[0].removesuffix('s'))
                 for n in nouns if not re.fullmatch(carriers, n[0])}
        if len(kinds) > 1:
            continue  # Two source kinds cannot share one inferred antecedent.
        candidates.append((i, next(iter(kinds), 'record')))
    if len(candidates) != 1:
        return text, False
    index, kind = candidates[0]
    same_source = mail + r'|信(?![心任念仰用號号息賴赖])' if kind == 'mail' else re.escape(kind) + ('s?' if kind.isascii() else '')
    referent = rf'(?:(?:selected|chosen)\s+|所選|選中|已選|所选|选中|已选)?(?:examples?|例子|範例|范例|{generic}|{same_source})'
    iteration = re.compile(rf'(?:for\s+)?(?:each|every)\s+{referent}|每[個个筆笔份封則则]?{referent}'
                           rf'|all\s+(?:selected|chosen)\s+(?:examples|records|{same_source})')
    presentation = re.compile(connective + output + r'\s*')
    possessive = r"(?:['’]s\s+|的|之)"
    local = r'\s*(?:its|their)\s+|\s*(?:它|其|它們|它们)的'
    predicate = (r'是否|有[無无]|沒有|没有|不存在|[均都][無无]|'
                 r'包含|含有|符合|屬於|属于|缺少|以外|之外|除外')
    spans = []
    for start, clause in clauses[index + 1:]:
        if re.search(predicate, clause):
            break  # No possessive/output ordering may hide a source predicate.
        refs = list(iteration.finditer(clause))
        verb = presentation.match(clause)
        owned = re.match(local, clause[verb.end():]) if verb else None
        if len(refs) == 1:
            ref = refs[0]
            before, after = clause[:ref.start()], clause[ref.end():]
            # Role ordering varies, but a fresh source predicate/count is not
            # an output field. A possessive or positive presentation binds it.
            leading = re.fullmatch(connective, before) and (
                presentation.match(after) or re.match(possessive, after))
            # Chinese nominal compounds need no immediate 的. Predicate/source
            # tails are not field labels and cannot borrow the selected scope.
            compound = ref[0].startswith('每') and re.match(r'[\u3400-\u9fff]', after) and not re.search(
                rf'{actions}|^(?:有|無|无|是)|[?？]', after,
            ) and not any(not re.fullmatch(carriers, n[0]) for n in re.finditer(sources, after))
            action_first = presentation.fullmatch(before) and (
                re.match(possessive + r'|\s+with\s+', after) or compound)
            trailing = verb and ref[0].startswith('for ') and not after.strip()
            if not (leading or action_first or trailing):
                break
            spans.append((start + ref.start(), start + ref.end()))
            distributive = re.search(rf'都(?=(?:要|需)?{output}\s*$)', clause) if leading else None
            if distributive:
                spans.append((start + distributive.start(), start + distributive.end()))
            if leading:
                verb = presentation.match(clause, ref.end())
                owned = re.match(local, clause[verb.end():]) if verb else None
        elif refs or not owned:
            break  # A new/unknown target or instruction ends selected scope.
        if owned:
            spans.append((start + verb.end(), start + verb.end() + owned.end()))
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + ' ' * (end - start) + text[end:]
    return text, True


def deterministic_query_class(query_text: str) -> str:
    """Classify a query without model calls, hidden state, or nondeterministic repair."""

    _require_nonempty_public_string(query_text, "query_text")
    normalized = _CITATION_PRESENTATION_SUFFIX.sub("", query_text.casefold())
    normalized = _CONDITIONAL_COMPLETENESS_DISCLOSURE.sub(
        lambda match: " " if match["disclosure"] is not None else match[0], normalized,
    )
    # Only a whole negated output directive is excluded from classification.
    # Positive exact requests and negative source predicates remain intact.
    quoted = r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|(?<!\w)\x27[^\x27]*\x27(?!\w)'
    normalized = re.sub(
        quoted + rf"|(?P<policy>(?<![^,;，；、。.!?！？])\s*(?:{_NEGATED_COMPLETENESS_DIRECTIVE.pattern})\s*(?=$|[,;，；、。.!?！？]))",
        lambda match: " " if match["policy"] is not None else match[0], normalized,
    )
    normalized = _bounded_selection_view(normalized)[0]
    # A field in a delimited excerpt is not an inventory of source records.
    # Mask only its local interrogative; quoted source predicates remain opaque.
    instruction = re.sub(quoted, " ", normalized)
    # A positive request to verify absence across the workspace needs complete
    # scope, not top-k evidence. Bind absence to a source-headed proposition;
    # nominal policy negation must not borrow a later source noun as its operand.
    confirmation = (
        r"^(?:(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
        r"(?:confirm|verify|prove|certify)\b|(?:請|请)?(?:能否|可否)?"
        r"(?:確認|确认|核實|核实|證明|证明))"
    )
    whole_workspace = (
        r"\b(?:entire|whole)\s+workspace\b|\b(?:anywhere\s+in|throughout|across)\s+"
        r"(?:the\s+)?workspace\b|整[個个]工作[區区]"
    )
    source = rf"(?:{_WORKSPACE_CONTENT_PATTERN.pattern}|\b(?:mail|emails?|messages?)\b|信件|郵件|邮件)"
    # A bare source head or one lexical modifier is closed before the existence
    # predicate; complements of unrelated nouns are not source noun phrases.
    english_source = rf"(?:[a-z][a-z0-9_-]*\s+)?{source}"
    english_absence = (
        rf"(?:that\s+)?(?:(?:(?:the\s+)?(?:{whole_workspace})\s+(?:contains?|has)"
        rf"|there\s+(?:is|are))\s+no\s+{english_source}"
        rf"|no\s+{english_source}\s+exists?\b"
        rf"|{english_source}\s+do(?:es)?\s+not\s+exist\b)"
    )
    # Close the source head with a locative or an explicit source qualifier,
    # never an unconsumed nominal complement. Qualifier objects are opaque.
    english_tail = (
        rf"(?:\s+(?:(?:in|within)\s+(?:the\s+)?)?(?:{whole_workspace}))?"
        r"(?:\s+(?:about|mentioning|matching)\s+[^,;，；。.!?！？]+)?"
    )
    cjk_source = rf"[\u3400-\u9fff]*?{source}"
    cjk_absence = (
        rf"(?:{whole_workspace})(?:內|内|中)?(?:完全)?(?:沒有|没有|不存在)(?:任何)?"
        rf"(?:{source}|(?:提到|提及)[^,;，；。!?？]+?的{cjk_source})\s*$"
        rf"|{cjk_source}在(?:{whole_workspace})(?:內|内|中)?(?:完全)?不存在\s*$"
    )
    for clause in re.split(r"[,，;；。.!?！？]", instruction):
        clause = clause.strip()
        action = re.match(confirmation, clause)
        proposition = clause[action.end():].strip() if action else ""
        if (action and re.search(whole_workspace, proposition)
                and (re.fullmatch(english_absence + english_tail, proposition)
                     or re.fullmatch(cjk_absence, proposition))):
            return "exact_set_or_inventory"
    if re.search(r"(?:只|僅|仅)(?:限|整理|回報|回报)(?:該|该|此|所引)?(?:片段|段落|欄|栏|列|行)", instruction) and not re.search(
        r"全部|所有|每", instruction,
    ):
        normalized = re.sub(
            quoted + r"|(?P<field>(?:片段|段落|該列|该列|此列|所引列)(?:的|之)"
            r"[^,;，；。!?？]{1,32}?欄(?:位)?(?:列了|列出|記載|记载|顯示|显示|包含)?哪些)",
            lambda match: match[0][:-2] if match["field"] is not None else match[0], normalized,
        )
    # A named subject's requirements/properties are descriptive source lookup,
    # not a corpus inventory merely because the question uses 哪些. Mask only
    # that subject-local interrogative; independent exact operations survive.
    targets = protected_reference_identifiers(instruction)
    if len(targets) == 1 and not re.search(
        r"\b(?:all|every|each|count|inventory|aggregate)\b|全部|所有|每|完整|"
        r"計算|计算|統計|统计|總數|总数|總計|总计|合計|合计|加總|加总|平均", instruction,
    ):
        target = r"(?<![a-z0-9._/-])" + re.escape(targets[0]) + r"(?![a-z0-9._/-])"
        requirement = target + r"\s*(?:要|需(?:要)?|應(?:該)?|应(?:该)?|必須|必须)\s*[\u3400-\u9fff]{0,12}哪些"
        attribute = target + r"\s*(?:的|之)[^,;，；。.!?！？]{1,40}?(?:是|有|為|为)哪些"
        def descriptive_question(match: re.Match[str]) -> str:
            if match["requirement"] is not None:
                return match[0][:-2]
            if match["attribute"] is not None:
                # A source-record noun headed set (e.g. attachments) stays exact;
                # arbitrary property names need no domain/field vocabulary.
                noun = re.sub(r"(?:是|有|為|为)哪些$", "", match[0])
                if re.search(rf"(?:{_WORKSPACE_CONTENT_PATTERN.pattern}|{'|'.join(_MAIL_CONTENT_MARKERS)}|資料列|数据行|行列)$", noun):
                    return match[0]
                return match[0][:-2]
            return match[0]  # Quoted source predicates are never instructions.
        normalized = re.sub(quoted + rf"|(?P<requirement>{requirement})|(?P<attribute>{attribute})",
                            descriptive_question, normalized)
    if re.search(r"(?:所有|全部|每)[^,;，；。!?？]{0,64}(?:沒有|没有|不存在|均無|都無)", normalized):
        return "exact_set_or_inventory"
    if re.search(rf"(?:有|共有)(?:幾|几)[{_CJK_RECORD_CLASSIFIERS}]", normalized):
        return "exact_set_or_inventory"
    # A source count noun is exact even without 多少. Require a noun boundary
    # so a source's 數據/數位 property does not become a record count.
    if re.search(
        rf"(?:{_WORKSPACE_CONTENT_PATTERN.pattern}|{'|'.join(_MAIL_CONTENT_MARKERS)})\s*[數数]"
        r"(?:量|目)?(?=$|[\s,，;；:：。.!?？]|是|為|为)", normalized,
    ):
        return "exact_set_or_inventory"
    # A concrete record's property amount is not a count of source records.
    # Every 多少 must belong to that shape; mixed cardinality/aggregation stays exact.
    identifiers = protected_reference_identifiers(normalized)
    subject = r"(?:的|之" + (r"|(?<![a-z0-9._/-])(?:" + "|".join(
        re.escape(identifier) for identifier in identifiers
    ) + r")(?![a-z0-9._/-])\s*" if identifiers else "") + r")"
    property_amount_spans = tuple(
        match.span() for match in re.finditer(
            subject + r"[^,，;；。!?？]{1,64}?(?:是|為|为)多少(?=[?？。.!;；，,、]|$)", normalized,
        )
    )
    scalar_amount = (
        bool(protected_reference_identifiers(normalized))
        and bool(property_amount_spans)
        # A requested calculation/statistic is not a stored scalar lookup.
        and not re.search(r"計算|计算|統計|统计|\b(?:calculate|compute|aggregate)\b", normalized)
        # Reuse source-noun grammar for record counts without a measure word.
        and not re.search(rf"(?:{_WORKSPACE_CONTENT_PATTERN.pattern})\s*[數数]", normalized)
        # Classifier + count is cardinality; unrelated 數 suffixes (係數) are not.
        and not re.search(
            rf"總數|总数|數目|数目|[{_CJK_RECORD_CLASSIFIERS}][數数]|總計|合計|加總|平均",
            normalized,
        )
        and all(
            any(start <= match.start() < end for start, end in property_amount_spans)
            for match in re.finditer("多少", normalized)
        )
    )
    if any(
        (re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", normalized)
        if term.isascii() else term in normalized)
        and not (term == "多少" and scalar_amount)
        for term in _EXACT_TERMS
    ):
        return "exact_set_or_inventory"
    output_verbs, _completion_markers, inventory_markers = _CJK_EXACT_OUTPUT_GRAMMAR_V1
    if any(term in normalized for term in output_verbs) and any(
        marker in normalized for marker in inventory_markers
    ):
        return "exact_set_or_inventory"
    if any(term in normalized for term in _RELATION_TERMS):
        return "relation_reasoning"
    if any(term in normalized for term in _SUMMARY_TERMS):
        return "global_summarization"
    return "evidence_lookup"


def supports_native_attachment_page(capabilities: Mapping[str, Any] | None) -> bool:
    contract = capabilities.get("query_contract") if isinstance(capabilities, Mapping) else None
    return isinstance(contract, Mapping) and contract.get("native_locator_kinds") == ["attachment_page"]


def validate_semantic_request_contract(
    value: Mapping[str, Any],
    *,
    available_source_families: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate the server-bound original request goal used across tool retries."""

    if (not isinstance(value, Mapping) or not _SEMANTIC_REQUEST_CONTRACT_FIELDS <= set(value)
            or set(value) - _SEMANTIC_REQUEST_CONTRACT_FIELDS - {"native_locator"}):
        raise ContractValidationError("semantic request contract shape is invalid")
    original_query_hash = value["original_query_hash"]
    query_class = value["query_class"]
    source_family_scope = value["source_family_scope"]
    requested_fields = value["requested_fields"]
    maximum_claim_strength = value["maximum_claim_strength"]
    if (
        not isinstance(original_query_hash, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", original_query_hash) is None
    ):
        raise ContractValidationError("semantic request contract query hash is invalid")
    if query_class not in SEMANTIC_QUERY_CLASSES:
        raise ContractValidationError("semantic request contract query class is invalid")
    if (
        not isinstance(source_family_scope, Sequence)
        or isinstance(source_family_scope, (str, bytes))
        or not 1 <= len(source_family_scope) <= SEMANTIC_REQUEST_MAX_SOURCE_FAMILIES
        or any(
            not isinstance(family, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", family) is None
            for family in source_family_scope
        )
        or len(set(source_family_scope)) != len(source_family_scope)
    ):
        raise ContractValidationError("semantic request contract source scope is invalid")
    if available_source_families is not None and not set(source_family_scope).issubset(
        set(available_source_families)
    ):
        raise ContractValidationError(
            "semantic request contract source scope is unavailable"
        )
    if (
        not isinstance(requested_fields, Sequence)
        or isinstance(requested_fields, (str, bytes))
        or len(requested_fields) > 8
    ):
        raise ContractValidationError(
            "semantic request contract requested fields are invalid"
        )
    normalized_requested_fields: list[str] = []
    for field_name in requested_fields:
        if (
            not isinstance(field_name, str)
            or not field_name.strip()
            or len(field_name.strip()) > 120
        ):
            raise ContractValidationError(
                "semantic request contract requested field is invalid"
            )
        normalized_field_name = field_name.strip()
        safe_public_string(normalized_field_name, "requested_field")
        normalized_requested_fields.append(normalized_field_name)
    if len(set(normalized_requested_fields)) != len(normalized_requested_fields):
        raise ContractValidationError(
            "semantic request contract requested fields are invalid"
        )
    if maximum_claim_strength != _CLAIM_STRENGTH_BY_CLASS[query_class]:
        raise ContractValidationError(
            "semantic request contract claim strength is invalid"
        )
    normalized = {
        "original_query_hash": original_query_hash,
        "query_class": query_class,
        "source_family_scope": list(source_family_scope),
        "requested_fields": normalized_requested_fields,
        "maximum_claim_strength": maximum_claim_strength,
    }
    if "native_locator" in value:
        locator = value["native_locator"]
        if (not isinstance(locator, Mapping) or set(locator) != {"kind", "page"}
                or locator["kind"] != "attachment_page" or type(locator["page"]) is not int
                or locator["page"] < 1 or query_class != "evidence_lookup"
                or "mail" not in source_family_scope):
            raise ContractValidationError("semantic native attachment page is invalid")
        normalized["native_locator"] = dict(locator)
    assert_public_payload_safe(normalized, "semantic_request_contract")
    return normalized


def route_semantic_query(
    *,
    query_text: str,
    requester_user_id: str,
    workspace_id: str,
    source_scope_ids: Sequence[str],
    effective_graph_view: EffectiveGraphView,
    allowed_relation_types: Sequence[str] = (),
    allowed_directions: Sequence[str] = ("out",),
    seed_node_ids: Sequence[str] = (),
    target_core_supertype_id: str | None = None,
    exact_inventory_kind: str | None = None,
    exact_filter_term_hashes: Sequence[str] = (),
    exact_projection_term_hashes: Sequence[str] = (),
    exact_column_value_hash_pairs: Sequence[tuple[str, str]] = (),
    exact_lexical_term_ledger: Sequence[tuple[str, str, str, str]] = (),
    exact_grammar_term_ledger: Sequence[tuple[str, str]] = (),
    exact_grammar_policy_fingerprint: str | None = None,
    exact_source_occurrence_provider_fingerprint: str | None = None,
    exact_identifier_term_hashes: Sequence[str] = (),
    exact_topic_term_hashes: Sequence[str] = (),
    exact_normalized_field: str | None = None,
    exact_predicate: str | None = None,
    exact_operator: str | None = None,
    limits: SemanticPlanLimits = DEFAULT_SEMANTIC_PLAN_LIMITS,
    authorized_source: AuthorizedSemanticSource | None = None,
    query_class_override: str | None = None,
) -> SemanticQueryPlan:
    """Build and validate the smallest deterministic plan for the query class."""

    resolved_source = _resolve_authorized_source(
        authorized_source=authorized_source,
        workspace_id=workspace_id,
        source_scope_ids=source_scope_ids,
    )
    if query_class_override is not None:
        if query_class_override not in SEMANTIC_QUERY_CLASSES:
            raise ContractValidationError("semantic query class override is invalid")
        if query_class_override == "exact_set_or_inventory":
            if not all(
                isinstance(value, str) and value.strip()
                for value in (exact_normalized_field, exact_predicate, exact_operator)
            ):
                raise ContractValidationError(
                    "semantic query class override is invalid"
                )
        elif any(
            isinstance(value, str) and value.strip()
            for value in (exact_normalized_field, exact_predicate, exact_operator)
        ):
            raise ContractValidationError("semantic query class override is invalid")
    query_class = (
        query_class_override
        if query_class_override is not None
        else deterministic_query_class(query_text)
    )
    relation_types = tuple(sorted(set(allowed_relation_types)))
    directions = tuple(sorted(set(allowed_directions)))
    allowed_paths = (
        tuple(
            (relation_type, direction)
            for relation_type in relation_types
            for direction in directions
        )
        if query_class == "relation_reasoning"
        else ()
    )
    inventory_kind = (
        exact_inventory_kind or _deterministic_inventory_kind(query_text)
        if query_class == "exact_set_or_inventory"
        else None
    )
    plan = SemanticQueryPlan(
        query_hash=sha256_json(query_text),
        query_class=query_class,
        source_kind=resolved_source.source_kind,
        source_scope_ids=tuple(sorted(set(source_scope_ids))),
        workspace_id=workspace_id,
        requester_user_id=requester_user_id,
        required_permissions=_PERMISSION_REQUIREMENTS_BY_CLASS[query_class],
        user_graph_revision_id=effective_graph_view.user_graph_revision_id,
        canonical_graph_revision_id=effective_graph_view.canonical_graph_revision_id,
        ontology_revision_id=effective_graph_view.ontology_revision_id,
        assembly_policy_id=effective_graph_view.assembly_policy_id,
        allowed_paths=allowed_paths,
        seed_node_ids=tuple(sorted(set(seed_node_ids))),
        max_hops=min(2, limits.max_hops) if query_class == "relation_reasoning" else 0,
        max_fanout=min(6, limits.max_fanout),
        candidate_limit=min(24, limits.max_candidates),
        result_limit=min(
            20 if query_class == "exact_set_or_inventory" else 10,
            limits.max_results,
        ),
        evidence_budget=min(48, limits.max_evidence),
        time_budget_ms=min(1_500, limits.max_time_budget_ms),
        repair_budget=min(1, limits.max_repairs),
        repair_attempt_count=0,
        claim_strength=_CLAIM_STRENGTH_BY_CLASS[query_class],
        exact_operation=(
            "inventory_with_count" if query_class == "exact_set_or_inventory" else None
        ),
        exact_inventory_kind=inventory_kind,
        exact_filter_term_hashes=(
            tuple(sorted(set(exact_filter_term_hashes)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_projection_term_hashes=(
            tuple(sorted(set(exact_projection_term_hashes)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_column_value_hash_pairs=(
            tuple(sorted(set(exact_column_value_hash_pairs)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_lexical_term_ledger=(
            tuple(exact_lexical_term_ledger)
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_grammar_term_ledger=(
            tuple(exact_grammar_term_ledger)
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_grammar_policy_fingerprint=(
            exact_grammar_policy_fingerprint
            if query_class == "exact_set_or_inventory"
            else None
        ),
        exact_source_occurrence_provider_fingerprint=(
            exact_source_occurrence_provider_fingerprint
            if query_class == "exact_set_or_inventory"
            else None
        ),
        exact_identifier_term_hashes=(
            tuple(sorted(set(exact_identifier_term_hashes)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_topic_term_hashes=(
            tuple(sorted(set(exact_topic_term_hashes)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_normalized_field=exact_normalized_field,
        exact_predicate=exact_predicate,
        exact_operator=exact_operator,
        target_core_supertype_id=target_core_supertype_id,
        include_superseded=False,
    )
    return validate_semantic_query_plan(
        plan,
        effective_graph_view=effective_graph_view,
        authorized_workspace_id=workspace_id,
        authorized_source_scope_ids=source_scope_ids,
        supported_relation_types=allowed_relation_types,
        limits=limits,
        allow_bounded_repair=True,
        authorized_source=resolved_source,
    )


def validate_semantic_query_plan(
    plan: SemanticQueryPlan,
    *,
    effective_graph_view: EffectiveGraphView,
    authorized_workspace_id: str,
    authorized_source_scope_ids: Sequence[str],
    supported_relation_types: Sequence[str],
    limits: SemanticPlanLimits = DEFAULT_SEMANTIC_PLAN_LIMITS,
    allow_bounded_repair: bool = True,
    authorized_source: AuthorizedSemanticSource | None = None,
) -> SemanticQueryPlan:
    """Validate pins and scope; the only repair is one cap-reducing pass."""

    if not isinstance(plan, SemanticQueryPlan):
        raise ContractValidationError("semantic query plan is invalid")
    repaired = _bounded_cap_repair(plan, limits=limits) if allow_bounded_repair else plan
    _validate_plan_strings(repaired)
    if repaired.query_class not in SEMANTIC_QUERY_CLASSES:
        raise ContractValidationError("semantic query class is unsupported")
    resolved_source = _resolve_authorized_source(
        authorized_source=authorized_source,
        workspace_id=authorized_workspace_id,
        source_scope_ids=authorized_source_scope_ids,
    )
    if repaired.source_kind != resolved_source.source_kind:
        raise ContractValidationError("semantic query source kind mismatch")
    authorized_sources = set(authorized_source_scope_ids)
    if not repaired.source_scope_ids or not set(repaired.source_scope_ids).issubset(
        authorized_sources
    ):
        raise ContractValidationError("semantic query plan would widen source scope")
    if repaired.workspace_id != authorized_workspace_id:
        raise ContractValidationError("semantic query workspace scope mismatch")
    if repaired.requester_user_id != effective_graph_view.requester_user_id:
        raise ContractValidationError("semantic query requester scope mismatch")
    if (
        repaired.user_graph_revision_id != effective_graph_view.user_graph_revision_id
        or repaired.canonical_graph_revision_id != effective_graph_view.canonical_graph_revision_id
        or repaired.ontology_revision_id != effective_graph_view.ontology_revision_id
        or repaired.assembly_policy_id != effective_graph_view.assembly_policy_id
    ):
        raise ContractValidationError("semantic query revision pin mismatch")
    expected_permissions = _PERMISSION_REQUIREMENTS_BY_CLASS[repaired.query_class]
    if repaired.required_permissions != expected_permissions:
        raise ContractValidationError("semantic query permission scope mismatch")
    if repaired.claim_strength != _CLAIM_STRENGTH_BY_CLASS[repaired.query_class]:
        raise ContractValidationError("semantic query claim strength is invalid")
    _validate_numeric_caps(repaired, limits=limits)
    _validate_query_class_shape(
        repaired,
        effective_graph_view=effective_graph_view,
        supported_relation_types=supported_relation_types,
    )
    repaired.to_safe_dict()
    return repaired


def _resolve_authorized_source(
    *,
    authorized_source: AuthorizedSemanticSource | None,
    workspace_id: str,
    source_scope_ids: Sequence[str],
) -> AuthorizedSemanticSource:
    expected_scope_ids = tuple(sorted(set(source_scope_ids)))
    if authorized_source is None:
        return validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=workspace_id,
            source_scope_ids=expected_scope_ids,
        )
    if not isinstance(authorized_source, AuthorizedSemanticSource):
        raise ContractValidationError("semantic query authorized source is invalid")
    if (
        authorized_source.workspace_id != workspace_id
        or authorized_source.source_scope_ids != expected_scope_ids
    ):
        raise ContractValidationError("semantic query authorized source scope mismatch")
    return authorized_source


def _bounded_cap_repair(
    plan: SemanticQueryPlan,
    *,
    limits: SemanticPlanLimits,
) -> SemanticQueryPlan:
    over_cap = (
        plan.max_hops > limits.max_hops
        or plan.max_fanout > limits.max_fanout
        or plan.candidate_limit > limits.max_candidates
        or plan.result_limit > limits.max_results
        or plan.evidence_budget > limits.max_evidence
        or plan.time_budget_ms > limits.max_time_budget_ms
        or plan.repair_budget > limits.max_repairs
    )
    if not over_cap:
        return plan
    if plan.repair_budget < 1 or plan.repair_attempt_count >= 1:
        raise ContractValidationError("semantic query plan exceeds execution caps")
    return replace(
        plan,
        max_hops=min(plan.max_hops, limits.max_hops),
        max_fanout=min(plan.max_fanout, limits.max_fanout),
        candidate_limit=min(plan.candidate_limit, limits.max_candidates),
        result_limit=min(plan.result_limit, limits.max_results),
        evidence_budget=min(plan.evidence_budget, limits.max_evidence),
        time_budget_ms=min(plan.time_budget_ms, limits.max_time_budget_ms),
        repair_budget=min(plan.repair_budget, limits.max_repairs),
        repair_attempt_count=plan.repair_attempt_count + 1,
    )


def _validate_plan_strings(plan: SemanticQueryPlan) -> None:
    for field_name, value in (
        ("query_hash", plan.query_hash),
        ("source_kind", plan.source_kind),
        ("workspace_id", plan.workspace_id),
        ("requester_user_id", plan.requester_user_id),
        ("user_graph_revision_id", plan.user_graph_revision_id),
        ("canonical_graph_revision_id", plan.canonical_graph_revision_id),
        ("ontology_revision_id", plan.ontology_revision_id),
        ("assembly_policy_id", plan.assembly_policy_id),
        ("claim_strength", plan.claim_strength),
    ):
        _require_nonempty_public_string(value, field_name)
    for field_name, values in (
        ("source_scope_ids", plan.source_scope_ids),
        ("required_permissions", plan.required_permissions),
        ("seed_node_ids", plan.seed_node_ids),
        ("exact_filter_term_hashes", plan.exact_filter_term_hashes),
        ("exact_projection_term_hashes", plan.exact_projection_term_hashes),
        (
            "exact_column_value_hash_pairs",
            tuple(
                value
                for pair in plan.exact_column_value_hash_pairs
                for value in pair
            ),
        ),
        (
            "exact_lexical_term_ledger",
            tuple(
                value
                for binding in plan.exact_lexical_term_ledger
                for value in binding
            ),
        ),
        (
            "exact_grammar_term_ledger",
            tuple(
                value
                for binding in plan.exact_grammar_term_ledger
                for value in binding
            ),
        ),
        ("exact_identifier_term_hashes", plan.exact_identifier_term_hashes),
        ("exact_topic_term_hashes", plan.exact_topic_term_hashes),
        (
            "relation_repair_identifier_term_hashes",
            plan.relation_repair_identifier_term_hashes,
        ),
        (
            "relation_repair_concept_term_hashes",
            plan.relation_repair_concept_term_hashes,
        ),
    ):
        for value in values:
            _require_nonempty_public_string(value, f"{field_name} entry")
    for relation_type, direction in plan.allowed_paths:
        _require_nonempty_public_string(relation_type, "allowed relation type")
        _require_nonempty_public_string(direction, "allowed direction")
    if plan.exact_operation is not None:
        _require_nonempty_public_string(plan.exact_operation, "exact_operation")
    if plan.exact_inventory_kind is not None:
        _require_nonempty_public_string(plan.exact_inventory_kind, "exact_inventory_kind")
    exact_source_fields = (plan.exact_normalized_field, plan.exact_predicate, plan.exact_operator)
    if any(value is not None for value in exact_source_fields) and not all(
        isinstance(value, str) and value for value in exact_source_fields
    ):
        raise ContractValidationError("exact source occurrence binding is incomplete")
    for term_hash in (
        *plan.exact_filter_term_hashes,
        *plan.exact_projection_term_hashes,
        *(
            value
            for pair in plan.exact_column_value_hash_pairs
            for value in pair
        ),
        *(
            value
            for term_hash, _role, column_hash, grounded_hash in (
                plan.exact_lexical_term_ledger
            )
            for value in (term_hash, column_hash, grounded_hash)
        ),
        *(term_hash for term_hash, _role in plan.exact_grammar_term_ledger),
        *plan.exact_identifier_term_hashes,
        *plan.exact_topic_term_hashes,
        *plan.relation_repair_identifier_term_hashes,
        *plan.relation_repair_concept_term_hashes,
    ):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", term_hash) is None:
            raise ContractValidationError("semantic query term hash is invalid")
    for _term_hash, role, _column_hash, _grounded_hash in (
        plan.exact_lexical_term_ledger
    ):
        if role not in _EXACT_QUERY_LEXICAL_ROLES:
            raise ContractValidationError(
                "semantic query lexical term role is invalid"
            )
    for _term_hash, role in plan.exact_grammar_term_ledger:
        if role not in EXACT_QUERY_GRAMMAR_ROLES:
            raise ContractValidationError(
                "semantic query grammar term role is invalid"
            )
    lexical_occurrence_hashes = tuple(
        term_hash
        for term_hash, _role, _column_hash, _grounded_hash in (
            plan.exact_lexical_term_ledger
        )
    )
    grammar_occurrence_hashes = tuple(
        term_hash for term_hash, _role in plan.exact_grammar_term_ledger
    )
    lexical_bindings_by_term: dict[str, set[tuple[str, str, str]]] = {}
    for term_hash, role, column_hash, grounded_hash in plan.exact_lexical_term_ledger:
        lexical_bindings_by_term.setdefault(term_hash, set()).add(
            (role, column_hash, grounded_hash)
        )
    if (
        len(set(plan.exact_lexical_term_ledger))
        != len(plan.exact_lexical_term_ledger)
        or any(
            len(bindings) > 1
            and (
                {role for role, _column_hash, _grounded_hash in bindings}
                != {"filter_value"}
                or len(
                    {
                        grounded_hash
                        for _role, _column_hash, grounded_hash in bindings
                    }
                )
                != 1
            )
            for bindings in lexical_bindings_by_term.values()
        )
        or len(set(grammar_occurrence_hashes)) != len(grammar_occurrence_hashes)
        or set(lexical_occurrence_hashes).intersection(
            grammar_occurrence_hashes
        )
    ):
        raise ContractValidationError(
            "semantic query grounding ledger is invalid"
        )
    for field_name, fingerprint in (
        (
            "exact_grammar_policy_fingerprint",
            plan.exact_grammar_policy_fingerprint,
        ),
        (
            "exact_source_occurrence_provider_fingerprint",
            plan.exact_source_occurrence_provider_fingerprint,
        ),
        (
            "relation_repair_policy_fingerprint",
            plan.relation_repair_policy_fingerprint,
        ),
        (
            "relation_repair_vocabulary_fingerprint",
            plan.relation_repair_vocabulary_fingerprint,
        ),
    ):
        if fingerprint is None:
            continue
        if re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint) is None:
            raise ContractValidationError(f"semantic query {field_name} is invalid")
    if plan.target_core_supertype_id is not None:
        _require_nonempty_public_string(
            plan.target_core_supertype_id,
            "target_core_supertype_id",
        )
        if plan.target_core_supertype_id not in CORE_SUPERTYPE_IDS:
            raise ContractValidationError("semantic query target type is unsupported")


def _validate_numeric_caps(
    plan: SemanticQueryPlan,
    *,
    limits: SemanticPlanLimits,
) -> None:
    for field_name, value, maximum, allow_zero in (
        ("max_hops", plan.max_hops, limits.max_hops, True),
        ("max_fanout", plan.max_fanout, limits.max_fanout, False),
        ("candidate_limit", plan.candidate_limit, limits.max_candidates, False),
        ("result_limit", plan.result_limit, limits.max_results, False),
        ("evidence_budget", plan.evidence_budget, limits.max_evidence, False),
        ("time_budget_ms", plan.time_budget_ms, limits.max_time_budget_ms, False),
        ("repair_budget", plan.repair_budget, limits.max_repairs, True),
        ("repair_attempt_count", plan.repair_attempt_count, 1, True),
    ):
        minimum = 0 if allow_zero else 1
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
            or value > maximum
        ):
            raise ContractValidationError(f"semantic query {field_name} is invalid")
    if plan.repair_attempt_count > plan.repair_budget:
        raise ContractValidationError("semantic query repair budget is invalid")


def _validate_query_class_shape(
    plan: SemanticQueryPlan,
    *,
    effective_graph_view: EffectiveGraphView,
    supported_relation_types: Sequence[str],
) -> None:
    supported = set(supported_relation_types)
    if plan.seed_node_ids:
        indexed_store = getattr(effective_graph_view, "_indexed_runtime_store", None)
        if indexed_store is not None:
            missing_seed = any(indexed_store.get_node(node_id) is None for node_id in plan.seed_node_ids)
        else:
            visible_node_ids = {node.node_id for node in effective_graph_view.visible_nodes}
            missing_seed = not set(plan.seed_node_ids).issubset(visible_node_ids)
        if missing_seed:
            raise ContractValidationError("semantic query seed scope is unavailable")
    if plan.query_class == "relation_reasoning":
        if plan.max_hops < 1 or not plan.allowed_paths:
            raise ContractValidationError("relation reasoning requires bounded paths")
        for relation_type, direction in plan.allowed_paths:
            if relation_type not in supported:
                raise ContractValidationError("semantic query contains an unsupported hop")
            if direction not in {"out", "in"}:
                raise ContractValidationError("semantic query direction is unsupported")
        if (
            plan.exact_operation is not None
            or plan.exact_inventory_kind is not None
            or plan.exact_filter_term_hashes
            or plan.exact_projection_term_hashes
            or plan.exact_column_value_hash_pairs
            or plan.exact_lexical_term_ledger
            or plan.exact_grammar_term_ledger
            or plan.exact_grammar_policy_fingerprint is not None
            or plan.exact_source_occurrence_provider_fingerprint is not None
            or plan.exact_identifier_term_hashes
            or plan.exact_topic_term_hashes
            or plan.exact_normalized_field is not None
        ):
            raise ContractValidationError("relation reasoning cannot carry exact execution")
        repair_fields_present = (
            bool(plan.relation_repair_identifier_term_hashes),
            bool(plan.relation_repair_concept_term_hashes),
            plan.relation_repair_policy_fingerprint is not None,
            plan.relation_repair_vocabulary_fingerprint is not None,
        )
        if any(repair_fields_present) and not all(repair_fields_present[1:]):
            raise ContractValidationError("relation fallback repair binding is incomplete")
        if any(repair_fields_present) and plan.repair_attempt_count != 1:
            raise ContractValidationError("relation fallback repair attempt is invalid")
        return
    if (
        plan.allowed_paths
        or plan.seed_node_ids
        or plan.max_hops != 0
        or plan.relation_repair_identifier_term_hashes
        or plan.relation_repair_concept_term_hashes
        or plan.relation_repair_policy_fingerprint is not None
        or plan.relation_repair_vocabulary_fingerprint is not None
    ):
        raise ContractValidationError("semantic query plan would widen graph scope")
    if plan.query_class == "exact_set_or_inventory":
        if plan.exact_operation != "inventory_with_count" or not plan.exact_inventory_kind:
            raise ContractValidationError("exact query requires structured inventory scope")
        expected_filter_hashes = tuple(
            sorted(set(plan.exact_identifier_term_hashes) | set(plan.exact_topic_term_hashes))
        )
        if plan.exact_filter_term_hashes != expected_filter_hashes:
            raise ContractValidationError("exact query filter slots are inconsistent")
        if set(plan.exact_filter_term_hashes).intersection(
            plan.exact_projection_term_hashes
        ):
            raise ContractValidationError(
                "exact query filter and projection slots overlap"
            )
        structured_fields_present = (
            bool(plan.exact_column_value_hash_pairs),
            bool(plan.exact_lexical_term_ledger),
            bool(plan.exact_grammar_term_ledger),
            plan.exact_grammar_policy_fingerprint is not None,
            plan.exact_source_occurrence_provider_fingerprint is not None,
        )
        if any(structured_fields_present):
            if not (
                plan.exact_column_value_hash_pairs
                and plan.exact_lexical_term_ledger
                and plan.exact_grammar_policy_fingerprint is not None
                and plan.exact_source_occurrence_provider_fingerprint is not None
            ):
                raise ContractValidationError(
                    "exact structured query binding is incomplete"
                )
            filter_pairs = tuple(
                sorted(
                    {
                        (column_hash, grounded_hash)
                        for (
                            _term_hash,
                            role,
                            column_hash,
                            grounded_hash,
                        ) in plan.exact_lexical_term_ledger
                        if role == "filter_value"
                    }
                )
            )
            projection_columns = tuple(
                sorted(
                    {
                        column_hash
                        for (
                            _term_hash,
                            role,
                            column_hash,
                            _grounded_hash,
                        ) in plan.exact_lexical_term_ledger
                        if role == "projection_field"
                    }
                )
            )
            if (
                filter_pairs != plan.exact_column_value_hash_pairs
                or tuple(
                    sorted(
                        {
                            value_hash
                        for _column_hash, value_hash in filter_pairs
                        }
                    )
                )
                != plan.exact_filter_term_hashes
                or projection_columns != plan.exact_projection_term_hashes
            ):
                raise ContractValidationError(
                    "exact structured query slots are inconsistent"
                )
        return
    if (
        plan.exact_operation is not None
        or plan.exact_inventory_kind is not None
        or plan.exact_filter_term_hashes
        or plan.exact_projection_term_hashes
        or plan.exact_column_value_hash_pairs
        or plan.exact_lexical_term_ledger
        or plan.exact_grammar_term_ledger
        or plan.exact_grammar_policy_fingerprint is not None
        or plan.exact_source_occurrence_provider_fingerprint is not None
        or plan.exact_identifier_term_hashes
        or plan.exact_topic_term_hashes
        or plan.exact_normalized_field is not None
    ):
        raise ContractValidationError("non-exact query cannot carry exact execution")


def _deterministic_inventory_kind(query_text: str) -> str:
    normalized = query_text.casefold()
    if "purchase order" in normalized or "採購單" in normalized or re.search(r"\bpo\b", normalized):
        return "purchase_order"
    if any(term in normalized for term in ("message", "email", "mail", "訊息", "郵件")):
        return "mail_observation"
    return "generic_identifier"


def repair_relation_plan_once(
    plan: SemanticQueryPlan,
    *,
    seed_node_ids: Sequence[str],
    required_identifier_term_hashes: Sequence[str],
    required_concept_term_hashes: Sequence[str],
    policy_fingerprint: str,
    vocabulary_fingerprint: str,
) -> SemanticQueryPlan:
    """Create the one scope-preserving relation fallback plan."""

    if plan.query_class != "relation_reasoning":
        raise ContractValidationError("relation fallback repair is unavailable")
    if plan.repair_budget < 1 or plan.repair_attempt_count >= plan.repair_budget:
        raise ContractValidationError("semantic relation repair budget is exhausted")
    identifier_hashes = tuple(sorted(set(required_identifier_term_hashes)))
    concept_hashes = tuple(sorted(set(required_concept_term_hashes)))
    if not concept_hashes:
        raise ContractValidationError("relation fallback concept scope is unavailable")
    if plan.seed_node_ids and not set(seed_node_ids).issubset(plan.seed_node_ids):
        raise ContractValidationError("relation fallback would widen seed scope")
    repaired = replace(
        plan,
        seed_node_ids=tuple(sorted(set(seed_node_ids))),
        repair_attempt_count=plan.repair_attempt_count + 1,
        relation_repair_identifier_term_hashes=identifier_hashes,
        relation_repair_concept_term_hashes=concept_hashes,
        relation_repair_policy_fingerprint=policy_fingerprint,
        relation_repair_vocabulary_fingerprint=vocabulary_fingerprint,
    )
    _validate_plan_strings(repaired)
    return repaired


def _require_nonempty_public_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} is required")
    safe_public_string(value, field_name)


def _canonical_permission_scope(value: PermissionScope) -> dict[str, Any]:
    if not isinstance(value, PermissionScope):
        raise ContractValidationError("semantic query permission scope binding is invalid")
    normalized = to_plain(value)
    if not isinstance(normalized, dict):
        raise ContractValidationError("semantic query permission scope binding is invalid")
    try:
        validate_permission_scope(normalized)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise ContractValidationError(
            "semantic query permission scope binding is invalid"
        ) from exc
    if set(normalized) not in (
        {"scope_type", "scope_id", "visibility"},
        {"scope_type", "scope_id", "visibility", "inherited_from"},
    ):
        raise ContractValidationError("semantic query permission scope binding is invalid")
    if normalized.get("scope_type") not in {
        "workspace",
        "mail_import_session",
        "project",
    } or normalized.get("visibility") != "restricted":
        raise ContractValidationError("semantic query permission scope binding is invalid")
    _require_nonempty_public_string(normalized.get("scope_id"), "permission_scope.scope_id")
    inherited_from = normalized.get("inherited_from")
    if inherited_from is not None:
        _require_nonempty_public_string(
            inherited_from,
            "permission_scope.inherited_from",
        )
    return normalized


__all__ = [
    "AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND",
    "AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND",
    "AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND",
    "GITHUB_PROJECT_OBSERVATION_SOURCE_KIND",
    "AuthorizedSemanticSource",
    "DEFAULT_SEMANTIC_PLAN_LIMITS",
    "EXACT_QUERY_GRAMMAR_ROLES",
    "SEMANTIC_CLAIM_STRENGTH_BY_CLASS",
    "SEMANTIC_QUERY_CLASSES",
    "SemanticPlanLimits",
    "SemanticQueryPlan",
    "authorized_permission_scope_matches",
    "deterministic_query_class",
    "is_ordinary_greeting",
    "repair_relation_plan_once",
    "route_semantic_query",
    "validated_authorized_semantic_source",
    "validate_semantic_request_contract",
    "validate_semantic_query_plan",
]
