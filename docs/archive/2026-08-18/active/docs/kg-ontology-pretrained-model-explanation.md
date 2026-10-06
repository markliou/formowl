# FormOwl KG + Ontology：預訓練模型與 Ontology 建構方式

## 一句話結論

目前 FormOwl **不是讓預訓練模型自動生成 ontology**。

在現有 `KG + ontology` 實驗中，預訓練模型主要是：

```text
BAAI/bge-large-en-v1.5
```

它只負責計算兩段文字的語意相似度。Ontology 的核心類型、階層、
domain mapping 與治理規則是由 FormOwl 規格、程式規則、資料候選與審核流程建立。

---

## 1. 預訓練模型是哪一個？

### 現行 GPU 實驗模型

```text
BAAI/bge-large-en-v1.5
```

用途：

- 將 entity、concept、文件片段等文字轉成 embedding。
- 計算兩個 embedding 的 cosine similarity。
- 產生可能相同或相關的 KG fusion candidate。

目前實驗 threshold：

```text
0.62
```

### 舊的 CPU fallback

```text
sentence-transformers/bert-base-nli-mean-tokens
```

這是舊的 CPU neural fallback，不是目前主要的 GPU benchmark 模型。

### 尚未成為現行預設的模型

```text
BAAI/bge-m3
```

`BGE-M3` 目前只是未來多語言 term/mention extraction 的 optional adapter
候選，尚未成為目前 ontology pipeline 的執行預設。

---

## 2. BGE 模型做了什麼？

流程如下：

```text
文字 A
  ↓
BGE embedding
  ↓
向量 A ─┐
        ├─ cosine similarity ─→ semantic similarity score
向量 B ─┘
  ↑
BGE embedding
  ↑
文字 B
```

例如：

```text
customer escalation policy
client complaint handling procedure
```

BGE 會將兩段文字轉成向量，再算出語意相似度。

如果相似度高於 threshold，系統可以提出：

```text
same_as_candidate
```

但這仍然只是 candidate，不是 canonical KG merge。

---

## 3. BGE 沒有做什麼？

BGE 不會自行決定：

- 公司應該有哪些 ontology types。
- `Customer` 是否應該是 `Organization`。
- `InvoiceApproval` 是否應該屬於 `Decision`。
- 哪一個 type 可以成為 canonical type。
- 兩個 scope 的 ontology 是否可以永久合併。

換句話說：

```text
BGE = 語意相似度模型
Ontology = 類型與治理規則
```

兩者是合作關係，不是由 BGE 直接產生 ontology。

---

## 4. FormOwl 的 Ontology 從哪裡來？

目前 ontology 分成三層。

### 4.1 Closed core types

FormOwl 規格固定八個核心類型：

```text
Person
Organization
Project
Artifact
Document
Event
Concept
Location
```

這些類型由 specification 定義，不是模型從資料中學出來的。

### 4.2 Coordination-frame core

企業協作行為使用穩定的 frame types：

```text
Request
Commitment
Decision
Assignment
StatusUpdate
StatusChange
Blocker
Risk
Issue
OpenQuestion
Deadline
Dependency
Escalation
Change
Exception
Constraint
```

例如一封信可能被表示成：

```text
Request
  actor: Sales Manager
  target: Quote v2
  deadline: 2026-07-20
```

### 4.3 Scoped domain packs

各部門或 domain 可以提出自己的 extension type，再映射到穩定 core：

```text
CustomerRequest     -> Request
CustomerCommitment  -> Commitment
QuoteApproval       -> Decision
InventoryShortage   -> Blocker
InvoiceApproval     -> Decision
PaymentDelay        -> Risk
```

Domain type 不會直接改寫 core ontology。它必須保留：

- scope
- source observations
- ontology revision
- aliases
- core mapping
- confidence
- review state

---

## 5. KG + Ontology 怎麼一起判斷？

完整判斷方式是：

```text
Observation
  ↓
CandidateMention / CandidateEntity
  ↓
BGE semantic similarity
  ↓
Ontology type compatibility
  ↓
same_as candidate / reject / defer for review
```

### Hard ontology gate

```text
相同 core type
  -> 保留 BGE similarity score

不同 core type
  -> score = 0
```

### Soft ontology gate

```text
相同 core type
  -> score 不變

不同 type、相同 parent
  -> score × 0.60

不相容 type
  -> score × 0.45
```

實際 production-style ontology helper 對低信心 type prediction 採用較保守的
soft prior；只有雙方 type 都是高信心且不相容時，才進行 hard reject。

---

## 6. 一個最容易理解的例子

假設有兩個名稱：

```text
左：Apple，type = Organization
右：Apple，type = Product
```

因為文字完全相同，BGE similarity 可能非常接近：

```text
1.0
```

如果只有 embedding，系統可能錯誤提出：

```text
Apple Organization == Apple Product
```

加入 ontology gate 後：

```text
Organization != Product
```

因此系統拒絕或降低這個 match。

Ontology 在這裡扮演的是：

```text
type-aware constraint / re-ranking layer
```

而不是由 BGE 自動生成的知識分類樹。

---

## 7. 現有實驗結果

20,000-pair ontology stress benchmark：

| 方法 | F1 | False Positive |
| --- | ---: | ---: |
| BGE only | 0.342860 | 10,177 |
| BGE + hard ontology gate | 0.757744 | 177 |

其中 10,000 個刻意建立的 cross-type stress false positives：

```text
10,000 -> 0
```

正確解讀是：

> 在已經有 core type 的情況下，ontology gate 可以阻止 embedding 將同名但
> 不同類型的物件錯誤合併。

這個結果不能證明 BGE 能自動建立 ontology，因為實驗中的 core type
主要來自 benchmark labels、規格與 fixture mapping。

---

## 8. 未來資料驅動的 Ontology 建構流程

FormOwl 的目標不是永遠手寫所有 domain ontology，而是建立受治理的
bottom-up ontology：

```text
RawResource
  ↓
Observation
  ↓
term / mention candidates
  ↓
候選類型與 alias
  ↓
映射到 closed core
  ↓
TypeDefinition / TypeMapping / TypeAlignmentCandidate
  ↓
policy 與人工審核
  ↓
scoped promoted type
  ↓
versioned ontology revision
```

候選 term/type 可以來自：

- Unicode、regex 與 CJK span。
- corpus frequency、document spread、PMI 與 entropy。
- gazetteer 與 suffix rules。
- 文件欄位、版面與附近角色詞。
- NER 或 embedding model。
- 跨文件、跨 modality 的重複證據。
- 已審核的 candidate 與 active-learning feedback。

模型可以協助產生 candidate，但不能直接寫入 canonical ontology。

---

## 9. SentencePiece 不是預訓練 Ontology Model

EXM 實驗也使用：

```text
jieba + SentencePiece
```

但這裡的 SentencePiece：

- 不是下載既有的 pretrained language model。
- 是使用目前 corpus 即時訓練的 BPE tokenizer。
- 只負責產生 term/token candidates。
- 不負責建立 canonical ontology。

目前穩定的 EXM candidate-admission default 是固定 scoring profile：

```text
frozen_profile_candidate_admission
```

它是基於 CJK、詞長、document frequency、organization suffix 與 protected
category 的固定規則，training examples 與 training epochs 都是零。

---

## 10. 最後整理

```text
BAAI/bge-large-en-v1.5
  -> 找語意相近的 KG candidates

Closed core + coordination frames + domain mappings
  -> 提供 ontology 結構

Ontology compatibility policy
  -> 過濾或降低不合理的 semantic matches

Review and governance
  -> 決定是否成為 scoped canonical type / graph state
```

因此目前最準確的描述是：

> FormOwl 使用 BGE 作為 KG semantic matching model，使用受治理的 scoped
> ontology 作為 type constraint。BGE 不會直接把 ontology 做出來。

## 對應程式位置

- BGE model 與 ontology ablation：
  `experiments/kg_bert_ablation/run_ontology_ablation.py`
- KG model profiles：
  `experiments/kg_bert_ablation/run_ablation.py`
- Core types 與 coordination frames：
  `python/formowl_contract/models.py`
- Type compatibility 與 alignment candidate：
  `python/formowl_graph/ontology.py`
- Coordination-frame domain packs：
  `python/formowl_graph/coordination_frames.py`
- EXM SentencePiece 與 candidate admission：
  `scripts/mail_full_pst_exm_lexical_ontology_eval.py`
- Ontology method：
  `docs/kg-research-method.md`
- Multimodal term/mention decision：
  `docs/multimodal-ontology-term-extraction-decision.md`
