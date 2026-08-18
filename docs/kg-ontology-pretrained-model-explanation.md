# FormOwl KG + Ontology：模型與方法說明

**現行方向：GitHub issue #56**
**狀態（2026-08-18）：方法目標已固定，但 runtime authority 仍是 `blocked`**

## 一句話結論

FormOwl 背後不是只靠一個「KG LLM」。正確設計是把模型角色拆開，並用
同一個回答模型公平比較 strong RAG 與 KG + ontology：

```text
BM25 + dense retrieval 找原始證據
KG 做跨來源實體整合、join、時間與 provenance
ontology 做 scoped、可審核、有限度的 soft scoring
exact set / count 交給 deterministic executor
LLM 只根據授權證據規劃或產生有 citation 的答案
```

目前不能宣稱 KG + ontology 已經比 RAG 好。現行 runtime 還是
`ascii_identifier_regex_v1`，而目標是
`jieba_sentencepiece_frozen_profile_candidate_admission_v1`；可執行 authority
gate 尚未通過。

## 1. 背後要用哪一個 LLM？

架構本身不綁死單一廠牌或單一模型。每次實驗必須分別記錄：

```text
query planner model（若有）
candidate extraction / entity-linking model（若有）
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

目前會 exit 1，因為：

- runtime 還沒使用 frozen Hybrid-v2 tokenizer/profile；
- raw source 到 Observation 的 completeness 未與 oracle 對齊；
- reports 未綁定同一 execution fingerprint；
- 缺少 same-pipeline real-source ablation；
- 缺少 real-user final-answer acceptance。

因此現在可以做 implementation 與 diagnostic POC，但不能做 methodology-quality
UAT、不能宣稱 KG/ontology superiority，也不能把 issue #56 關閉。

## 9. 最後整理

- 長期方向：用 graph 整合異質資料，這個方向保留。
- retrieval 方向：不是 KG 取代 RAG，而是 strong RAG + graph guidance。
- ontology 方向：small core、scoped domain packs、data-first、soft scoring。
- 模型方向：角色分離、同模型公平比較、manifest 固定，不靠換模型偷得分。
- anti-fitting：holdout 不得參與 tokenizer、alias、ontology、threshold 或 prompt。
- exact set：deterministic executor，不從 top-k 猜完整答案。
- storage：PostgreSQL/pgvector 維持 canonical baseline，不做 Neo4j migration。
