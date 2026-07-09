# PROJECT_SPEC.md
### ISAP Data Engineer Selection Project — Government Budget Disbursement × Government Workforce

> Language note: เขียนแบบ Thai-English ปนกัน ให้เข้าใจง่าย ตามที่ขอ
> Status: **PLANNING ONLY** — ยังไม่เขียน code ในเอกสารนี้
> Author role: Junior Data Engineer (ผู้สมัคร)

---

## 0. TL;DR (อ่านอันเดียวจบ)

เรามีข้อมูล 2 แหล่งจากภาครัฐ ที่เผยแพร่เป็น Excel:

1. **CGD — ผลการเบิกจ่ายงบประมาณ** (กรมบัญชีกลาง) → อัปเดต **บ่อย** (รายสัปดาห์/รายเดือน), ชื่อไฟล์ = วันที่ของรายงาน
2. **OCSC — กำลังคนภาครัฐ** (สำนักงาน ก.พ.) → อัปเดต **ปีละครั้ง** (yearbook รายปีงบประมาณ)

ทั้งสองไฟล์ **ไม่ใช่ dataset สะอาด** แต่เป็น "รายงานที่ทำใน Excel" (มี title, header หลายชั้น, merged cell, footnote, สูตร Excel, sheet ที่เป็นกราฟล้วน ๆ).

**กลยุทธ์หลัก (สำคัญที่สุด):** เราจะ **ไม่** พยายามดูดทุก sheet. เราจะ **เลือก sheet ที่สะอาดและมีความหมายเชิงวิเคราะห์** จำนวนน้อย แล้วสร้าง pipeline ที่ถูกต้อง + อธิบายได้ + ดูแลรักษาง่าย. นี่คือสิ่งที่ Senior DE อยากเห็นจาก Junior — scope ให้เป็น ไม่ over-engineer.

Warehouse ที่แนะนำ = **DuckDB** (default) หรือ PostgreSQL (ถ้าอยากดู "จริงจัง" กว่า). Star-schema แบบเบา ๆ: 2 fact tables + conformed dimensions.

---

## 1. Requirement Breakdown & Scoring Rubric (คะแนนเต็ม 120)

| ข้อ | สิ่งที่ต้องส่ง | คะแนน | จะทำที่ step ไหน |
|---|---|---|---|
| 1 | ออกแบบ Data Warehouse + อธิบายเหตุผล | 10 + 10 = **20** | §4, §5 (Step 2) |
| 2 | EDA & Data Profiling ต่อ dataset + อธิบายปัญหา | 10 + 10 = **20** | §7 (Step 1) |
| 3a | Pipeline: extraction 15 / cleaning 15 / loading 5 / code quality 5 | **40** | §6 (Step 3–5) |
| 3b | ตรวจทุกเดือนว่ามี dataset ใหม่ไหม | **10** | §9 (Step 6–7) |
| 3c | ถ้ามีไฟล์ใหม่ (โครงสร้างเหมือนเดิม) ดูดเข้าได้ไม่พัง | **10** | §9 (Step 6–7) |
| 4 | ข้อเสนอแนะต่อ Senior DE | **20** | §11 (Step 9) |
| 5 | GitHub repo + Demo ตอนสัมภาษณ์ | บังคับ | ทุก step |
| 6 | ใช้ AI ได้ แต่ต้องอธิบาย code เองได้ | บังคับ | ทุก step |

**ข้อสังเกตเชิงกลยุทธ์:** ข้อ 3 (60 คะแนน) คือหัวใจ. ข้อ 3b+3c (20 คะแนน) ให้รางวัลกับ **automation ที่ทนต่อไฟล์ใหม่** — แปลว่า design ต้อง **config-driven** (ไม่ hardcode) ตั้งแต่แรก. ข้อ 6 บังคับให้เราเลือก tool ที่ **อธิบายได้ทุกบรรทัด** → ห้ามลาก Airflow/Spark มาโชว์.

---

## 2. What the Data Actually Is (ตรวจของจริงแล้ว)

### 2.1 CGD — `2026_07_03.xlsx` (ผลการเบิกจ่าย)
- 15 sheets = 15 รายงานย่อย: `1.สรุปภาพรวม`, `2.กระทรวง`, `3.หน่วยงาน`, `4.หน่วยงาน(ใช้จ่าย)`, `5.อบจ.`, `7.เทศบาล`, `10.รัฐวิสาหกิจ`, `11-14.จังหวัด`, `15.กองทุนฯ` ฯลฯ
- หน่วย = **ล้านบาท**
- โครงสร้างแต่ละ sheet: row 0–2 = title/วันที่/หน่วย, row 3–4 = **header 2 ชั้นแบบ grouped** (รายจ่ายประจำ / รายจ่ายลงทุน / รวม แต่ละกลุ่มมี 6 คอลัมน์ย่อย), แล้วตามด้วย data, ปิดท้ายด้วย footnote/ที่มา
- มี **สูตร Excel สด ๆ** ในคอลัมน์ร้อยละ (เช่น `=F6*100/B6`) และแถวรวม (`=B6+B10`)
- `2.กระทรวง` มี `รหัสกระทรวง` (ministry code) ต่อท้าย → เป็น key ที่ค่อนข้างเสถียร

### 2.2 OCSC — `thaigovmanpower2567_4.xlsx` (กำลังคนภาครัฐ 2567)
- ~68 sheets ชื่อตาม **เลขหน้า** ของ yearbook (`11`, `12`, `17-29`, `99-113` …) + `ปกหน้า`, `สารบัญ`, `แนวโน้ม 10 ปี`, `ปกหลัง`
- **หลาย sheet เป็นกราฟล้วน ๆ** → อ่านค่า cell ได้แค่ title (data density = 0–1 แถว)
- `สารบัญ` = map หัวข้อ → ช่วงหน้า (ใช้เป็น metadata ได้)
- Sheet ที่สะอาดสุด: **`12`** = ภาพรวมกำลังคนภาครัฐ (3 คอลัมน์: ประเภทกำลังคน / จำนวน(คน) / ร้อยละ) — ตารางตรง ๆ
- Sheet ที่รวยข้อมูลแต่ **โหดสุด**: **`17-29`** = แยกตามส่วนราชการ × ประเภทบุคลากร — header 4 ชั้น, merged name column (A–C), แถวลำดับชั้น (1 → 1.1 → 1.2), แถว `รวม` ปนอยู่ในข้อมูล, สูตร `=SUM(...)`, และ sub-split `เงินใน/เงินนอกงบประมาณ`

---

## 3. Project Scope (ขอบเขตที่จะทำจริง — strict)

### ✅ In scope (Core — ต้องทำให้เสร็จและเนี้ยบ)
| Source | Sheet | กลายเป็น | เหตุผลที่เลือก |
|---|---|---|---|
| CGD | `2.กระทรวง` | `fact_disbursement` (grain: period × ministry × expense_type) | สะอาดสุดของ CGD, มี ministry code, ครอบคลุมทั้งประเทศ |
| OCSC | `12` | `fact_workforce_summary` (grain: fiscal_year × personnel_category) | สะอาดสุดของ OCSC, ตีความง่าย, analyst ใช้ได้ทันที |

### 🟡 Stretch (ทำถ้าเหลือเวลา — และต้องกล้าตัดถ้าเสี่ยง)
| Source | Sheet | หมายเหตุความเสี่ยง |
|---|---|---|
| CGD | `3.หน่วยงาน` | โครงสร้างคล้าย `2.กระทรวง` แต่ granularity ละเอียดกว่า |
| OCSC | `17-29` | **HIGH RISK** — header 4 ชั้น + merged + hierarchical + total rows. ทำเป็นตัวอย่างว่าเรารับมือ header โหดได้ แต่ห้ามให้มันทำ core พัง |

### ❌ Out of scope (ประกาศชัด ๆ ว่าไม่ทำ + เหตุผล)
- Sheet กราฟล้วน ๆ (`11`, `แนวโน้ม 10 ปี`, `ปกหน้า/หลัง`) → ไม่มี data ให้ดูด
- การ **join ระดับแถว** ระหว่าง 2 แหล่ง (เอา headcount มาหารเงินเบิกจ่ายต่อคน) → **ชื่อหน่วยงานไม่ตรงกัน** ระหว่าง OCSC กับ CGD (ดู §10). จะไม่ปลอมว่า join ได้สะอาด
- การดูดทุก 68 sheet → over-engineering, อธิบายไม่ได้, automate ไม่ได้แบบ generic

---

## 4. Data Warehouse Design (ข้อ 1 — การออกแบบ)

**รูปแบบ:** Star-schema เบา ๆ (2 fact + conformed dimensions). Layer แบ่งเป็น `raw → staging → warehouse`.

### 4.1 Dimensions
- **`dim_date`** — period_key, report_date, month, quarter, fiscal_year(BE/CE), is_month_end. (CGD ใช้ report_date; OCSC ใช้ fiscal_year)
- **`dim_ministry`** — ministry_key, ministry_code (จาก CGD), ministry_name_th, source_name_raw. (ค่อย ๆ สะสมชื่อดิบไว้ debug)
- **`dim_expense_type`** — 'รายจ่ายประจำ' / 'รายจ่ายลงทุน' / 'รวม'
- **`dim_personnel_category`** — ข้าราชการ / ทหาร / ตำรวจ / ครู / พนักงานส่วนตำบล ฯลฯ (จาก OCSC sheet 12)
- **`dim_source`** — source_id, agency ('CGD'/'OCSC'), source_url, file_name, ingested_at (metadata/lineage)

### 4.2 Facts
**`fact_disbursement`** — grain = 1 แถวต่อ (report_date × ministry × expense_type)
- FK: date_key, ministry_key, expense_type_key, source_id
- Measures (ล้านบาท): budget_after_transfer, allocated, spending_plan, po_reserved, disbursed, remaining
- Derived: disbursed_pct (**คำนวณเองจาก disbursed/budget**, ไม่พึ่งสูตร Excel)

**`fact_workforce_summary`** — grain = 1 แถวต่อ (fiscal_year × personnel_category)
- FK: date_key(ปี), personnel_category_key, source_id
- Measures: headcount (คน), share_pct (คำนวณเอง)
- **`hierarchy_level`** (0=grand total, 1=subtotal, 2=leaf category) — **เพิ่มหลัง EDA (Step 1)**
- **`parent_category_key`** (FK กลับไปยัง personnel_category ของแม่, null สำหรับ grand total) — **เพิ่มหลัง EDA (Step 1)**
- **`is_leaf`** (boolean, ลัดสำหรับ analyst: `WHERE is_leaf = true` = ผลรวมถูกต้อง ไม่ double count)

> **⚠️ Finding จาก EDA (ดู `reports/eda_ocsc.txt`):** sheet `12` ไม่ใช่ 29 หมวดหมู่อิสระ แต่เป็น hierarchy 2 ชั้น (grand total → 2 subtotal → 22 leaf) — verified ด้วยผลรวมจริง (children ของ 'ข้าราชการ' รวมได้ 1,756,606 ตรงกับ subtotal เป๊ะ, children ของ 'กำลังคนประเภทอื่น' รวมได้ 1,247,879 ตรงกับ subtotal เป๊ะ, 2 subtotal รวมกันตรงกับ grand total 3,004,485 เป๊ะ). ถ้าไม่ tag hierarchy_level, `SUM(headcount)` ของ analyst จะ overcount ~3 เท่า.

### 4.3 Layer model
```
raw/       เก็บไฟล์ Excel ต้นฉบับ + hash + วันที่โหลด (immutable, ไม่แก้)
staging/   ตารางแบน ๆ ที่ parse ออกมาแล้ว ยังไม่ join dimension
warehouse/ dim_* + fact_* พร้อมให้ Analyst query
```

---

## 5. Why This Design Suits Data Analysts (ข้อ 1 — การอธิบายเหตุผล)

1. **Star schema = analyst ทุกคนคุ้น** → join fact กับ dim แล้ว group by ได้ทันที (BI tool อย่าง Power BI / Looker / Excel Pivot ชอบรูปนี้)
2. **แยก 2 fact ไม่ยัดรวม** → เพราะ grain ต่างกัน (เงินรายเดือน vs คนรายปี). ยัดรวมจะได้ตารางที่ผิดหลัก grain และหลอก analyst
3. **Conformed dimension (`dim_ministry`, `dim_date`)** → อนาคตถ้าชื่อหน่วยงาน map กันได้ ก็ค่อยเชื่อม 2 fact ผ่าน dim เดียวกัน โดยไม่ต้องรื้อ
4. **คำนวณ % เอง ไม่พึ่งสูตร Excel** → ตัวเลขถูกต้อง reproducible แม้เปิดไฟล์ด้วย tool ที่ไม่ recalc
5. **เก็บ raw layer + lineage (`dim_source`)** → analyst/auditor ตรวจย้อนได้ว่าเลขมาจากไฟล์ไหน วันไหน (สำคัญมากกับข้อมูลราชการ)
6. **Long format (unpivot)** → ประเภทบุคลากร/ประเภทรายจ่ายเป็น "แถว" ไม่ใช่ "คอลัมน์" → filter/aggregate ง่ายกว่า wide format มาก

---

## 6. ETL / ELT Pipeline Architecture (ข้อ 3a)

เลือก **ELT-lite**: Extract ไฟล์ → โหลดดิบเข้า staging → Transform ใน SQL/pandas → warehouse.

```
[Source website]
   │  (Step 6: latest-file detector)
   ▼
extract.py ──▶ raw/<source>/<date>.xlsx  + manifest (hash, url, ts)
   │
   ▼
parse.py   ──▶ staging (แบน, ต่อ sheet, ตาม config)
   │
   ▼
clean.py   ──▶ ซ่อม header หลายชั้น, ตัด title/footnote/total row,
   │            unpivot, normalize ชื่อ, recompute %, cast type
   ▼
load.py    ──▶ dim_* + fact_* (idempotent upsert ตาม period/year)
   │
   ▼
validate.py ─▶ ตรวจ schema/ค่า (fail loud ถ้าเพี้ยน)
```

**Config-driven (หัวใจของข้อ 3c):** แต่ละ source มีไฟล์ config (เช่น YAML) ระบุ: sheet name, แถว header เริ่มที่ไหน, คอลัมน์ไหนคือ measure, unit, mapping ชื่อคอลัมน์. ไฟล์ใหม่ที่ "โครงสร้างเหมือนเดิม" → แค่ config เดิมก็ผ่าน โดยไม่ต้องแก้ code.

**Stack (เรียบ + อธิบายได้ทุกบรรทัด):** Python + `pandas` + `openpyxl` + `duckdb` (หรือ `psycopg2`+Postgres) + `requests`/`beautifulsoup4` (detector) + `pytest`.

---

## 7. EDA & Data Profiling Strategy (ข้อ 2)

ทำเป็น script/notebook ที่ output รายงานปัญหาต่อ dataset. สิ่งที่จะ profile: จำนวน sheet, sheet ไหนมี data จริง, row/col count, dtype, null, duplicate, unit, ค่าติดลบ/ผิดปกติ, และ **ปัญหาเชิงโครงสร้าง**.

### ปัญหาที่ **เจอจริงแล้ว** (จะเขียนเป็นคำตอบข้อ 2)

**CGD (`2026_07_03.xlsx`):**
- Header 2 ชั้นแบบ grouped + merged cell → pandas อ่านตรง ๆ ได้ header เพี้ยน
- Title 3 แถวบน + footnote/ที่มา ท้าย sheet ปนกับ data
- คอลัมน์ % เป็น **สูตร Excel** ไม่ใช่ค่า → ต้อง recompute
- แถว `รวมทั้งสิ้น` / subtotal ปนกับแถวข้อมูล → ต้องกรองออก
- หน่วยเป็นล้านบาท (ต้องบันทึก unit ให้ชัด)
- คอลัมน์ `แผนการใช้จ่าย` หลายกระทรวงเป็น 0 → ต้องเช็คว่า 0 จริงหรือ missing

**OCSC (`thaigovmanpower2567_4.xlsx`):**
- 68 sheet โครงสร้างต่างกันหมด → generic parser เป็นไปไม่ได้
- หลาย sheet เป็นกราฟ ไม่มี cell data
- ชื่อ sheet = เลขหน้า ไม่สื่อความหมาย (ต้องพึ่ง `สารบัญ`)
- `17-29`: header 4 ชั้น, merged, hierarchical numbering, total rows, สูตร SUM, `เงินใน/เงินนอก` sub-split
- Thai text + ช่องว่างท้ายชื่อ (`'65 '`, `'องค์กรอิสระ '`) → ต้อง strip
- ตัวเลข % เป็น float ยาว (เช่น 58.4661…) → เก็บ raw แต่ round ตอนแสดง

---

## 8. (ย้ายไปรวมกับ §7)

---

## 9. Monthly Automation Strategy (ข้อ 3b + 3c)

**3b — ตรวจว่ามีไฟล์ใหม่ไหม (detector):**
- CGD: เว็บมีหน้า listing ที่โชว์รายงานพร้อมวันที่ (3 ก.ค. / 30 มิ.ย. / 26 มิ.ย. …). Detector จะ (1) เปิดหน้า listing, (2) หา entry ล่าสุด + วันที่, (3) เทียบกับ `manifest` ที่เคยโหลด, (4) ถ้าใหม่กว่า → download
- OCSC: เป็นรายปี. Detector เช็คว่ามี yearbook ปีใหม่ (เช่น 2568) โผล่ไหม. ปกติทั้งเดือนจะ "ไม่มีใหม่" ซึ่งถูกต้อง
- **Idempotency:** เก็บ hash ของไฟล์. ไฟล์เดิม hash เดิม → ข้าม ไม่โหลดซ้ำ ไม่ insert ซ้ำ

**3c — ไฟล์ใหม่โครงสร้างเหมือนเดิม ดูดเข้าได้ไม่พัง:**
- เพราะ parser อ่านจาก **config** ไม่ใช่ hardcode → ไฟล์ใหม่ที่ layout เดิมก็ผ่าน
- มี **schema validation**: ถ้าคอลัมน์/header ไม่ตรง config → **หยุดและ alert** (ไม่โหลดข้อมูลผิด ๆ เงียบ ๆ). นี่คือจุดที่ได้คะแนน code quality

**Scheduler (แนะนำแบบ student-friendly):**
- Default: **GitHub Actions** `schedule: cron` รันเดือนละครั้ง → รัน detector + tests, เปิด issue/log ถ้าเจอไฟล์ใหม่ (visible, ฟรี, ไม่ต้องเปิดเครื่องไว้)
- ทางเลือก: **cron** บนเครื่อง local เขียน DuckDB file
- **ไม่ใช้ Airflow** — over-engineering สำหรับ scope นี้ และอธิบายยากในสัมภาษณ์

---

## 10. Testing Strategy (สนับสนุนข้อ 3 + ข้อ 4)

1. **Unit tests** (pytest) บน pure function ของ `clean.py`: ใส่ตารางปลอมเล็ก ๆ → เช็คว่า header ถูกซ่อม, total row ถูกตัด, % ถูก recompute
2. **Schema validation tests**: ป้อน input ที่ header เพี้ยน → ต้อง raise error (พิสูจน์ข้อ 3c ว่า fail loud)
3. **Data quality checks** (รันหลัง load): ไม่มี null ใน key, disbursed ≤ budget, headcount ≥ 0, ผลรวมแต่ละประเภท ≈ แถว `รวม` ในต้นฉบับ (reconciliation)
4. **Smoke E2E**: รัน pipeline กับไฟล์ตัวอย่างที่ commit ไว้ → เช็คว่า fact table ได้จำนวนแถวตามคาด
5. **Idempotency test**: รัน load ไฟล์เดิม 2 รอบ → จำนวนแถวไม่เพิ่ม

---

## 11. High-Risk Parts (strict — ต้องรู้ก่อนเริ่ม)

| ความเสี่ยง | ระดับ | ผลถ้าไม่ระวัง | วิธีคุม |
|---|---|---|---|
| **Web scraping เว็บราชการ** | 🔴 สูง | HTML เปลี่ยน / โดนบล็อค IP / ผิด ToS → detector พัง | cache raw file, มี manual-download fallback, ไม่ยิงถี่, เขียน parser ให้ fail loud |
| **Join ชื่อหน่วยงาน 2 แหล่ง** | 🔴 สูง | ชื่อไม่ตรง → เลขต่อหัวผิด, หลอก analyst | **ไม่ join ระดับแถวใน core**; ทำ mapping dict แยกเป็น stretch เท่านั้น |
| **พึ่ง cached ค่าสูตร Excel** | 🟠 กลาง | tool อื่นเปิดได้ None → % หาย | recompute เองจาก raw numbers |
| **Header หลายชั้น/merged** | 🟠 กลาง | layout ขยับ → map คอลัมน์ผิดเงียบ ๆ | pin ผ่าน config + schema validation |
| **สมมติ "โครงสร้างเหมือนเดิม" (3c)** | 🟠 กลาง | ปีใหม่ layout เปลี่ยน → โหลดผิด | validation ต้อง raise ไม่ใช่ warn |
| **Over-scope 68 sheets** | 🔴 สูง | ทำไม่เสร็จ/อธิบายไม่ได้ | scope ตาม §3, ประกาศ out-of-scope ชัด |
| **ปน BE/CE year (2567 vs 2024)** | 🟢 ต่ำ | รายงานผิดปี | เก็บทั้ง fiscal_year_be และแปลง ce ใน dim_date |

---

## 12. Step-by-Step Implementation Roadmap

> แต่ละ step ตอนลงมือจริงจะให้: (1) ไฟล์ที่สร้าง/แก้ (2) code เป๊ะ ๆ (3) คำสั่งรัน (4) output ที่คาด (5) วิธี test (6) สิ่งที่ต้องเข้าใจก่อนไปต่อ

- **Step 0 — Repo skeleton & env** *(Sonnet)*: โครงโฟลเดอร์, venv, `requirements.txt`, README, `.gitignore`, เลือก warehouse engine
- **Step 1 — EDA & profiling** *(Sonnet เขียน / Opus review)* → คำตอบ **ข้อ 2**
- **Step 2 — Warehouse DDL** *(Opus design → Sonnet เขียน DDL)* → คำตอบ **ข้อ 1**
- **Step 3 — Extractor + config** *(Sonnet)*: อ่าน sheet ที่เลือก, เก็บ raw + manifest → **ข้อ 3a (extraction 15)**
- **Step 4 — Cleaner/transformer** *(Sonnet)*: ซ่อม header, ตัด total, unpivot, recompute % → **ข้อ 3a (cleaning 15)**
- **Step 5 — Loader** *(Sonnet)*: idempotent upsert เข้า dim/fact → **ข้อ 3a (loading 5)**
- **Step 6 — Latest-file detector** *(Sonnet, Opus review ความเสี่ยง scraping)* → **ข้อ 3b**
- **Step 7 — Scheduler (GitHub Actions/cron) + schema validation** *(Sonnet)* → **ข้อ 3c**
- **Step 8 — Tests** *(Sonnet)*: unit + validation + smoke + idempotency → **code quality 5**
- **Step 9 — Suggestions to Senior + Docs + Demo script + Interview prep** *(Opus)* → **ข้อ 4** + ข้อ 5/6

**Definition of Done (core):** pipeline รันจบ → มี `fact_disbursement` + `fact_workforce_summary` ใน warehouse, ผ่าน validation, tests เขียว, detector เช็คไฟล์ใหม่ได้, README + demo อธิบายได้ทุกบรรทัด.

---

## 13. Decisions — ✅ LOCKED

- **Warehouse engine:** ✅ **DuckDB** (single file `warehouse.duckdb`, SQL, zero server)
- **Scheduler:** ✅ **GitHub Actions** (`schedule: cron`, รันเดือนละครั้ง, ฟรี, visible)
- **Scope:** ✅ **Core only** — `fact_disbursement` (CGD `2.กระทรวง`) + `fact_workforce_summary` (OCSC sheet `12`). Stretch sheets (`17-29`, `3.หน่วยงาน`) เลื่อนไว้ก่อน, ค่อยพิจารณาหลัง core เขียว

### (เดิม) ตัวเลือกที่พิจารณา

1. **Warehouse engine:** DuckDB (แนะนำ, ง่าย, ไฟล์เดียว, SQL) **vs** PostgreSQL (จริงจังกว่า, ต้องตั้ง server/Docker)
2. **Scheduler:** GitHub Actions (แนะนำ) **vs** local cron
3. **Stretch sheets** (`3.หน่วยงาน`, `17-29`): ทำหรือข้ามไปก่อน

*(รายละเอียด engine/scheduler อยู่ใน §6 และ §9)*
