# 標註結果的通用資料層設計（Claude，2026-11-08）

狀態：草案，待使用者同意。方法學權威仍為 valid but blocked；本設計是診斷性實作，不構成方法學完成或 UAT 通過主張。

## 1. 要解決的問題（2026-11-07 在 8088 實測得到）

1. 候選事實只存在 JSONL 檔＋啟動時的記憶體索引，只能用料號／採購單號查；「依欄位值找項目」（產地＝中國）完全無路可走。
2. 表格被逐格標註成碎片：一列原本同時有料號、PO、CRD、ETD、數量，標註後變成只有一個日期、沒有料號的碎列。
3. 值沒有統一寫法：`2026/7/3` vs `2026-07-03`；`中國/China/CN/china/中国`。
4. 因上述原因，2026-11-07 已加了三個針對性補丁（quote_mention 索引、補驗不受 16 KiB 限制、引文附表頭）。新設計落地後，前兩個補丁要拿掉；表頭改由記錄本身攜帶。

根因不是資料庫種類，而是標註結果從未被整理成「一筆筆完整記錄＋統一值＋一種通用查詢」。

## 2. 核心概念

**記錄（record）**：來源裡天然的一筆資料，一律保留原生出處。
- 表格列：xlsx/csv 附件的一列、郵件內嵌表格的一列（已有原生 row/cell observation 與 `table_structure.column_name`）。
- PDF 明細行：採購單 PDF 的一行品項（目前只有版面文字，需 LLM 標註）。
- 文字段落：郵件正文／文件段落中的陳述（LLM 標註，現行 gen4）。

**值（value）**：記錄的一個欄位。每個值同時保留：原欄名、對應的本體屬性（可為空）、原字串、統一後的值、值型別、角色（例如日期是「要求」「承諾出貨」「實際」）、引文位置。

**實體（entity）**：料號、採購單、供應商、公司等可識別對象，以「型別＋統一鍵」去重。記錄透過值連到實體，跨來源的連結（PDF 採購單 ↔ 郵件回覆 ↔ 附件 BOM）就靠同一實體，不靠引文剛好提到。

本體維持小核心：沿用現有 mapping 的屬性（part_number、manufacturer_part_number、po_number、po_date、delivery_date、quantity、origin_country…），只新增「值型別」與「日期角色」兩種描述，不為個別問題加屬性。

## 3. 建立記錄的三條路（全部離線、可續跑）

### 3.1 原生表格：照結構讀，不逐格問模型
1. 對每張原生表取「表頭簽章」＝正規化後的欄名序列。
2. 每個**不同的簽章**只請本地 Gemma 判斷一次：每一欄對應哪個本體屬性、日期欄是什麼角色（例：CRD→delivery_date/requested；ETD→delivery_date/estimated_ship；COO→origin_country）。輸入是欄名＋最多 5 列樣本；輸出是候選對照，存檔並可審核。現有 mapping 的別名（PO No.、產地、COO…）先直接套用，模型只補沒對上的欄。
3. 之後該簽章的所有列都用程式直接轉成記錄：一列一筆，所有欄位都在，沒對上屬性的欄也照原欄名保留（仍可文字查詢）。
4. 沒有表頭的表（今天看到的部分正文表格）：退回 3.3 的段落路徑，不猜欄名。

預期效果：同一份供應商週報反覆出現的表頭只問一次，模型呼叫數從「每格一次」降到「每種表頭一次」。

### 3.2 PDF 明細行：沿用現有標註，但按行組成記錄
現有 pdf_original/pdf_children 匯出已有 po_number、po_date、delivery_date、quantity、part_number，同一行品項的值共用同一段版面引文。以「同一來源觀測＋同一行引文」把值組成一筆記錄；文件表頭值（P/O No.、P/O Date）掛在文件層，再繼承到該文件每一行（沿用 1aacd50b 的表頭延續規則）。不重跑 PDF 標註。

### 3.3 文字段落：沿用 gen4 標註
gen4 繼續跑。段落標註的值以「同一來源單元」組成記錄；沒有料號的碎值仍保留，但只在有明確實體值時才連到實體。

## 4. 值的統一（依型別，不依個別值）

| 型別 | 統一方式 | 原字串 |
|---|---|---|
| 日期 | 年月日完整時轉 ISO（2026/7/3→2026-07-03）；缺年或含糊（TBD、W23）保留為未解析，不猜 | 保留 |
| 國家 | 用公開標準國名資料（ISO 3166 代碼＋CLDR 多語名稱）對照成二碼代碼；含城市的「中国昆山」取國家部分；對不上就未解析 | 保留 |
| 數量 | 去千分位轉數字，單位另存 | 保留 |
| 識別碼 | 去頭尾空白、統一大小寫，供比對；顯示用原字串 | 保留 |

不寫任何料號、供應商、國家專屬規則；國名對照來自公開標準資料，不是手寫清單。

## 5. 儲存：PostgreSQL（專案既定）

```text
record(record_id, kind[table_row|pdf_line|passage], source_observation_id, source_hash,
       document_id, mail_message_id, sent_at, header_signature_id, permission_scope, review_status)
record_value(record_id, column_name_raw, property_id NULL, raw_value, norm_value, value_type,
             date_role NULL, quote, native_locator, citation_hash)
entity(entity_id, entity_type, norm_key)
record_entity(record_id, entity_id, via_property)
header_signature(header_signature_id, column_names[], column_mapping JSONB, mapping_status)
```

- 索引：`(property_id, norm_value)`、`(entity_type, norm_key)`、`record_entity(entity_id)`。
- `column_mapping` 用 JSONB，不同表格欄位不固定也能存（NoSQL 那種彈性在這裡就有）。
- 所有列都是 pending_review 候選；正式採用仍走既有 review/governance，不寫 canonical。
- 權限：查詢時以 permission_scope 過濾；實體連結不授予存取權。

## 6. 查詢：只有一種結構化查詢

回答模型的查詢代理產生一個查詢計畫（擴充現有 SemanticQueryPlan，不另建新模組）：

```json
{"filters":[{"property":"origin_country","op":"in","values":["中國"]}],
 "return":["part_number","manufacturer_part_number","origin_country"],
 "group_by":"part_number", "order_by":null, "include_unmapped_text":true}
```

- 屬性只能從本體清單選；過濾值送進第 4 節同一個統一器（「中國」→CN），所以「中國/China/CN」自然對上，不靠模型或程式列舉寫法。
- 程式把計畫轉成參數化 SQL（屬性白名單、無字串拼接），**逐筆完整清點**，回傳：符合總數、每筆記錄的原欄名＋原值＋統一值＋日期角色＋寄件日期＋引文。超過顯示上限時明確寫「共 N 筆，顯示 M 筆」，可續頁。
- 例：
  - 「PART-A 的交期」＝ filter part_number＝PART-A，return 所有 date 型值（含角色、寄件日期），依實體分組。PDF 採購單與郵件 ETD 回覆因連到同一料號實體而一起出現。
  - 「產地是中國的料件」＝ filter origin_country＝CN，return 料號類屬性，依料號分組。
- 計畫無法對應任何屬性時（純敘述問題），照舊走強 RAG（BM25＋dense）文字檢索。結構化結果與文字檢索可同時提供，模型回答時兩者都附引文。

## 7. 對 8088 的影響

- 新增：查詢計畫的 filters/return 欄位、結構化執行器、記錄庫唯讀連線。
- 拿掉：candidate_fact_index 記憶體索引、quote_mention、preferred 補驗特例（記錄在建庫時已完成來源雜湊驗證；查詢時只需核對來源雜湊未變）。
- 候選事實表的呈現改為直接呈現記錄（原欄名本來就在記錄裡，不再另附表頭）。

## 8. 驗證（以真實資料判定，不以這兩題調參）

1. 離線建庫：先只做 3.1 原生表格＋3.2 PDF 行，報告記錄數、表頭簽章數、模型呼叫數、各屬性統一成功率。
2. 題目：今天的兩題，加上**至少 8 題事先寫好、從未用來調整的新題**，涵蓋：依料號查欄位、依欄位值找項目、依採購單找料、計數、跨來源（PDF＋郵件）合併、否定題（查無時要說「在已建記錄中未找到」而非「不存在」）。題目寫好先封存雜湊再跑。
3. 判定：每題對照原始來源人工核對召回與正確率；只看到這兩題變好不算通過。
4. 回歸：完整測試，非豁免新增失敗 0。
5. 通過後才改 8088，部署前問使用者。

## 9. 分階段

| 階段 | 內容 | 需要 GPU | 預估 |
|---|---|---|---|
| P1 | 原生表格記錄＋表頭簽章對照＋值統一，離線建庫（PostgreSQL 容器） | 少量（每種表頭一次） | 1–2 天 |
| P2 | PDF 行組記錄、實體連結 | 否 | 0.5–1 天 |
| P3 | 查詢計畫擴充＋結構化執行器，離線跑 10 題核對 | 回答模型少量 | 1–2 天 |
| P4 | 8088 換上新路徑、移除補丁、部署 | 否 | 0.5 天 |

gen4 不停；P1 的表頭判斷與 gen4 共用 GPU，排在 gen4 線路空檔或以單一線路執行。
