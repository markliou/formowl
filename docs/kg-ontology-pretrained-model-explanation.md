# FormOwl KG + Ontology：模型與方法說明

**現行方向：GitHub issue #56**

**狀態（2026-10-18）：產品語意標註規格已釐清，功能待實作／待測；方法論仍 blocked**

## 一句話結論

FormOwl 背後不是只靠一個「KG LLM」。正確設計是把模型角色拆開，並用
同一個回答模型公平比較 strong RAG 與 KG + ontology：

```text
BM25 + dense retrieval 找原始證據
LLM 離線分批讀取郵件、文件及所有範圍內附件，產生可回溯來源的語意候選
KG 做跨來源實體整合、join、時間與 provenance
ontology 提供實體／事件／主張／關係／時間語意及文件標註；scoring 只是其中一環
exact set / count 交給 deterministic executor
查詢 LLM 解讀問題、透過標註選來源，再讀原文生成有 citation 的答案
```

目前不能宣稱 KG + ontology 已比 RAG 好。`ascii_identifier_regex_v1` 是
2026-08-18 的歷史紀錄，不是現行 runtime 宣告。authority manifest 與
2026-10-02 dev-container 紀錄已對齊 frozen tokenizer，但不等於 source completeness
或方法論驗收通過。現在狀態須由 executable authority 決定；host 缺少相依套件
不能取代 canonical container 證據。

## 1. 背後要用哪一個 LLM？

架構本身不綁死單一廠牌或單一模型。每次實驗必須分別記錄：

```text
query planner model（若有）
semantic-reading model（ontology-aware 必須記錄）及 entity-linking model（若有）
embedding model
reranker model（若有）
final answer model
reasoning effort、prompt、schema、context budget、decoding settings
```

其中最重要的公平性規則是：

> strong RAG、RAG + entity、RAG + KG、RAG + KG + ontology 等所有比較 arm，
> 必須使用同一個 final answer LLM、同一 reasoning effort、同一 prompt、
> 同一 evidence/context budget。

所以「換更強 LLM」不能被算成 KG 或 ontology 的進步。若模型改了，就要建立
新的 experiment version，不能繼續宣稱是同一次 paired comparison。

### 歷史上用過的模型

- `BAAI/bge-large-en-v1.5`：歷史 GPU candidate embedding / matching 實驗。
- `sentence-transformers/bert-base-nli-mean-tokens`：舊 CPU fallback。

這兩者都是 embedding model，不是 ontology model，也不是 final answer LLM。
目前 active methodology 尚未指定一個可宣稱為 production answer model 的名稱；
必須等 execution manifest 固定模型、prompt、設定與 hash，並通過 authority gate。

歷史 document-first browser POC 使用 Codex sidecar 只證明一個受限的文件檢索與
合成路徑，不代表 KG/ontology 的正式 answer-model 決策。

## 2. 會不會又從測試題目 fitting？

不允許。資料用途必須隔離：

```text
calibration corpus -> 建 tokenizer/profile、protected identifier vocabulary
development corpus -> 調 threshold、做 error analysis
evaluation corpus  -> frozen diagnostic run
independent holdout -> 一次最終 frozen run
transfer holdout    -> 不同來源類型的泛化驗證
```

independent holdout 的題目與標準答案不得拿來：

- 訓練 SentencePiece；
- 新增 alias、synonym 或 entity merge；
- 建 ontology type/frame mapping；
- 修改 graph 規則、query router、threshold、prompt 或 scoring；
- 挑選「剛好會過」的模型。

如果 holdout 暴露問題，可以開下一個版本修正，但必須換新的 sealed holdout；不能
修完再把原題成績算成同一次正式驗證。

## 3. Strong RAG 在架構中的角色

Strong RAG 不是要被移除，而是基礎能力與比較基準：

```text
BM25 lexical retrieval
+ dense retrieval
+ deterministic fusion
+ evidence reranking
+ 相同 citation / answer-claim contract
```

KG + ontology 只有在下列問題上應該提供額外價值：

- 同一實體出現在 email、calendar、ticket、document 等不同來源；
- 需要多跳 relation join；
- 需要 current / historical / superseded state；
- 需要辨識 contradiction 與 provenance；
- 需要 exact set、inventory、count 或 aggregation。

若最後實驗沒有達到預先登記的改善門檻，就保留 strong RAG 當回答預設；KG 仍可
用於異質資料整合、治理、provenance 與 lifecycle，但不能宣稱 retrieval superiority。

## 4. Ontology 從哪裡來？

不是由 LLM 憑空建立，也不是從 UAT 題目倒推。採用 data-first、scoped 方法：

1. 小而穩定的跨領域 core；
2. source adapter 保留自己的 local type；
3. calibration/development evidence 提出 domain term、frame、alias 候選；
4. 經 evidence、scope、provenance 與 reviewer 決定是否 promoted；
5. 每次變更形成新的 `OntologyRevision`。

候選 core 包含 Actor、Person、Organization、Artifact、Document、
Communication、Event、Claim、Identifier、Project、Case、WorkItem、
TimeInterval、StateTransition、Location。

Email message、calendar event、ticket、drive document 都保留原本 source type，
再映射到 shared core；不把 mail-specific schema 當成整個企業 ontology。

### 文件標註不是「字串切開就算完成」

依 [SPEC §3.1.1](../SPEC.md#311-explicit-execution-modes-and-ontology-aware-uat-contract)，
先保存原文與原生座標，再以 LLM 分批讀完整宣告範圍並整合跨段落／信件／附件
脈絡。規則、regex、embedding 可輔助找識別碼或候選，不能代替語意閱讀。
每個單位記錄 annotated / pending / unsupported / failed；讀完沒有主張可以是
零候選，但沒讀到、被截斷、附件解析失敗不能記成零候選成功。

標註要連到特定實體、項次、事件／主張、時間角色、原文位置及更新關係，而非
只掛一個「交期」標籤。交期承諾、出貨日、發票日不是同一欄；較新的信件也不
代表整張訂單被取代。跨文件關係及 supersedes 都要有來源支持，canonical
發布仍經審核或已授權治理政策。

產品要求分成 direct_evidence_baseline 與 ontology_aware_uat 兩種證明範圍，
不是另開兩套服務，也不是已部署的旗標。後者全量驗收要有完整語意處理及實際
標註使用證據；前者仍能查原文。缺標註不能證明沒有資料，也不能讓有證據的
回答全部停擺；補查仍受 SPEC §7.3.1 所有要求欄位皆缺少的條件及預算約束。
以既有 owners 保留批次 checkpoint，來源或 profile 改變才增量處理及新增 revision，
不因使用者每問一題就重新標註。

## 5. Hard gate 與 soft ontology

可以 hard fail closed 的項目：

- permission / tenant / workspace / grant；
- schema 與 relation arity；
- evidence lineage；
- revision pins；
- canonical write preconditions；
- exact-set coverage contract。

只能當 soft signal 的項目：

- 推測 entity type；
- frame compatibility；
- alias / synonym mapping；
- 推測 relation；
- preferred ontology path。

預設 retrieval 只給 capped additive bonus。推測 mismatch 不加分，但不能把原本已
admit 的正確證據刪掉或歸零。歷史 hard type/frame gate 只保留為 negative
ablation，不再是 active default。

## 6. KG + Ontology 如何比 RAG 多做事情？

```text
query
  -> typed router
  -> validated SemanticQueryPlan
  -> BM25 + dense retrieval
  -> entity linking
  -> bounded graph traversal
  -> temporal / provenance / coverage filter
  -> capped ontology bonus
  -> evidence-bundle rerank
  -> deterministic executor 或 cited LLM answer
```

每個 graph hop 都必須回到授權的 Observation。不能只用 node label 或模型記憶回答。
每一跳都有 hop、edge type、fan-out、candidate、time、token budget。

Exact set、all、count、inventory、missing、duplicate、definitive negative 不能由 top-k
ranking 推斷，必須走 deterministic structured executor，並回報 coverage 是否完整。

## 7. 怎麼證明真的比 RAG 好？

至少比較：

1. strong hybrid RAG；
2. RAG + entity linking；
3. RAG + candidate KG；
4. RAG + KG + soft ontology；
5. legacy hard gate negative ablation；
6. exact-set 類題目的 deterministic executor。

所有 arm 共享 source snapshot、permission、tokenizer、answer LLM、prompt、budget、
evaluator 與硬體環境。

建議初始 replacement gate：

- graph-required strata final-answer correctness 至少比 strong RAG 高 10 個百分點，
  paired confidence interval 為正；
- direct lookup 退步不超過 2 個百分點；
- citation support precision 至少 95%；
- no-answer false positive 不惡化；
- permission/private evidence leakage 為 0；
- latency 與成本符合預先登記預算。

評估必須看 final answer，不只看 retrieval score。

## 8. 現在為什麼還是 blocked？

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

現行 manifest 的四項方法論 gate 仍 blocked：

- raw source 到 Observation 的 completeness 未與 oracle 對齊；
- reports 未綁定同一 execution fingerprint；
- 缺少 same-pipeline real-source ablation；
- 缺少 real-user final-answer acceptance。

因此現在可以做 implementation 與 diagnostic POC，但不能做 methodology-quality
UAT、不能宣稱 KG/ontology superiority，也不能把 issue #56 關閉。
命令實際 exit code 依當次環境決定；host 缺 tokenizer 相依時可能是 invalid/exit 2，
不可說成 canonical runtime 已退回 regex。這次文件修改沒有變更 frozen 實驗。

產品驗收依 SPEC §15.6：從網頁輸入、以網頁答案及引用核對原始資料；至少 mail+
附件及獨立專案／文件兩類案例，保留一般聊天。背景完成、MCP 有呼叫、API 測試
通過都不算；有來源可答卻只說查不到仍是失敗，不可算「安全回答通過」。

## 9. 最後整理

- 長期方向：用 graph 整合異質資料，這個方向保留。
- retrieval 方向：不是 KG 取代 RAG，而是 strong RAG + graph guidance。
- ontology 方向：small core、scoped domain packs、data-first、soft scoring。
- 模型方向：角色分離、同模型公平比較、manifest 固定，不靠換模型偷得分。
- anti-fitting：holdout 不得參與 tokenizer、alias、ontology、threshold 或 prompt。
- exact set：deterministic executor，不從 top-k 猜完整答案。
- storage：PostgreSQL/pgvector 維持 canonical baseline，不做 Neo4j migration。
