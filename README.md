# Ammonia Diagnostics API v2

> **Live API:** https://cpfbackend2-0.onrender.com

REST API สำหรับวิเคราะห์ประสิทธิภาพและวินิจฉัยปัญหาระบบทำความเย็นแอมโมเนีย (Single-stage refrigeration) พัฒนาด้วย FastAPI + MongoDB + CoolProp

---

## Features

- คำนวณ **COP, Q_e, Power, m_dot** จากข้อมูล sensor จริง
- วิเคราะห์ **Superheat / Subcooling / Pressure Ratio**
- สร้าง **P-H Diagram** พร้อม Saturation Dome และ Cycle Points (1→2→3→4)
- ระบบ **Alarm** แจ้งเตือนปัญหา เช่น Low COP, High Superheat, High Condensing Temp
- รองรับ **ค่า assume อัตโนมัติ** เมื่อ sensor บางตัวไม่มีข้อมูล (SH = 5K, η_is = 0.70)
- บันทึกและดึงประวัติข้อมูลจาก **MongoDB**

---

## Tech Stack

| Component       | Library/Tool                        |
|-----------------|-------------------------------------|
| Framework       | FastAPI                             |
| Thermodynamics  | CoolProp (IIR Reference State)      |
| Database        | MongoDB (Motor async driver)        |
| Validation      | Pydantic                            |
| Numerics        | NumPy                               |
| Server          | Uvicorn                             |
| Testing         | pytest + pytest-asyncio + pytest-cov |

---

## Installation

```bash
# 1. Clone repo
git clone <repo-url>
cd <project-dir>

# 2. สร้าง virtual environment (แนะนำ)
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 3. ติดตั้ง dependencies
pip install fastapi uvicorn motor pydantic python-dotenv CoolProp numpy

# 4. ตั้งค่า environment variable
cp .env.example .env
# แก้ไข MONGO_DETAILS ใน .env
```

### ไฟล์ `.env`

```
MONGO_DETAILS=mongodb://localhost:27017
```

---

## Run Server

```bash
python main.py
# หรือ
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Testing

### 1. ติดตั้ง dependencies สำหรับ Test

```bash
pip install pytest pytest-asyncio pytest-cov httpx anyio
```

> ติดตั้งทุกอย่างในครั้งเดียว:
>
> ```bash
> pip install fastapi uvicorn motor pydantic python-dotenv CoolProp numpy \
>             pytest pytest-asyncio pytest-cov httpx anyio
> ```

### 2. โครงสร้างไฟล์

```
project/
├── main.py          ← API หลัก
├── test_main.py     ← ชุด test ทั้งหมด
├── .env             ← ตัวแปรสภาพแวดล้อม (ไม่ commit)
└── .env.example     ← template
```

### 3. รัน Test

**รันพื้นฐาน (เฉพาะผ่าน/ไม่ผ่าน):**

```bash
python -m pytest test_main.py -v
```

**รันพร้อม Coverage Report แบบครบ:**

```bash
python -m pytest test_main.py --cov=main --cov-branch --cov-report=term-missing -v
```

**รันพร้อม HTML Report (เปิดดูในเบราว์เซอร์ได้):**

```bash
python -m pytest test_main.py --cov=main --cov-branch --cov-report=term-missing --cov-report=html -v
# เปิดดูที่ htmlcov/index.html
```

### 4. อ่านผลลัพธ์ Coverage

```
Name      Stmts   Miss Branch BrPart  Cover   Missing
-----------------------------------------------------
main.py     278      0    102      0   100%
-----------------------------------------------------
```

| คอลัมน์   | ความหมาย |
|-----------|----------|
| `Stmts`   | จำนวน statement (บรรทัดโค้ด) ทั้งหมด |
| `Miss`    | บรรทัดที่ **ไม่ถูก** execute → ควรเป็น 0 |
| `Branch`  | จำนวน branch (if/else/try) ทั้งหมด |
| `BrPart`  | branch ที่ผ่านแค่บางทาง → ควรเป็น 0 |
| `Cover`   | % coverage รวม → เป้าหมาย 100% |
| `Missing` | บรรทัดหรือ branch ที่ยังขาด |

### 5. Coverage ที่ได้

| ประเภท              | คำอธิบาย                                           | ผล     |
|---------------------|----------------------------------------------------|--------|
| **Statement Coverage** | ทุกบรรทัดถูก execute อย่างน้อย 1 ครั้ง         | ✅ 100% |
| **Branch Coverage**    | ทุก if/else/try ทำงานทั้งฝั่ง True และ False   | ✅ 100% |
| **Path Coverage**      | ครอบคลุมทุก logic path ของฟังก์ชันหลัก          | ✅ 100% |

> **หมายเหตุ:** Path Coverage วัดจาก branch combinations ที่ test ครอบคลุมใน `diagnose_compressor` และ `compute_cycle_points` ซึ่งรวมถึง mode `measured` vs `assumed` ทุก path

### 6. Test Cases ที่ครอบคลุม

| กลุ่ม | จำนวน | สิ่งที่ทดสอบ |
|-------|--------|------------|
| `safe_round` | 7 | None, float, int, negative, string → except branch |
| `diagnose_compressor` | 32 | ทุก path: measured/assumed, alarms, cop=0, h2=h1, exception |
| `compute_cycle_points` | 13 | all points, η measured/assumed, fallback, exception |
| `build_saturation_dome` | 6 | structure, monotonicity, loop exception → continue |
| `POST /api/metrics` | 4 | success, with timestamp, minimal fields, missing required |
| `GET /api/metrics` | 7 | list, empty, no timestamp, start only, end only, both, no filter |
| `GET /api/ph-diagram` | 9 | latest, 404, by timestamp, not found, record_id, string ts, None ts |
| `__main__` block | 1 | uvicorn.run ถูก call |
| **รวม** | **84** | |

---

## API Endpoints

### `POST /api/metrics` — บันทึกข้อมูลและวิเคราะห์

**Request Body:**

```json
{
  "compressor_id": "COMP-01",
  "timestamp": "2025-01-01T10:00:00+07:00",
  "sp_kg": 1.5,
  "dp_kg": 12.0,
  "st_c": -5.0,
  "dt_c": 85.0,
  "liquid_temp_c": 30.0,
  "current_amp": 45.0,
  "evaporator_room_temp_c": 2.0,
  "condenser_temp_c": 35.0
}
```

| Field | Type | Required | คำอธิบาย |
|-------|------|----------|----------|
| `compressor_id` | string | ✅ | รหัส Compressor |
| `sp_kg` | float | ✅ | Suction Pressure (kg/cm²g) |
| `dp_kg` | float | ✅ | Discharge Pressure (kg/cm²g) |
| `st_c` | float | ❌ | Suction Temperature (°C) — ถ้าไม่ใส่ assume SH = 5K |
| `dt_c` | float | ❌ | Discharge Temperature (°C) — ถ้าไม่ใส่ assume η_is = 0.70 |
| `liquid_temp_c` | float | ❌ | Liquid Line Temperature (°C) |
| `current_amp` | float | ❌ | Current (A) — ใช้คำนวณ Power |
| `evaporator_room_temp_c` | float | ❌ | อุณหภูมิห้องเย็น (°C) |
| `condenser_temp_c` | float | ❌ | อุณหภูมิน้ำ/อากาศ Condenser (°C) |

**Response:**

```json
{
  "status": "Success",
  "analysis": {
    "q_e_kw": 120.5,
    "power_kw": 45.2,
    "cop": 2.67,
    "superheat_suc": 8.3,
    "subcooling": 5.1,
    "pressure_ratio": 5.4,
    "m_dot_kgh": 1250.0,
    "alarms": [],
    "modes": {
      "sh_mode": "measured",
      "dt_mode": "measured"
    },
    "enthalpy": {
      "t_evap_c": -10.5,
      "t_cond_c": 38.2,
      "h1": 1450.2,
      "h2": 1620.8,
      "h2s": 1598.4,
      "h3": 325.1,
      "eta_is_pct": 86.8,
      "q_l_kgkg": 1125.1,
      "w_comp_kgkg": 170.6
    },
    "systems": {
      "sensor": { "status": "Normal", "text": "Superheat = 8.3" },
      "condenser": { "status": "Unknown", "text": "--" }
    }
  }
}
```

---

### `GET /api/metrics/{compressor_id}` — ดึงประวัติข้อมูล

**Query Parameters:**

| Parameter | Type | Default | คำอธิบาย |
|-----------|------|---------|----------|
| `limit` | int | 2000 | จำนวน record สูงสุด |
| `start` | datetime | - | เริ่มต้นช่วงเวลา (ISO 8601) |
| `end` | datetime | - | สิ้นสุดช่วงเวลา (ISO 8601) |

**ตัวอย่าง:**

```
GET /api/metrics/COMP-01?limit=100&start=2025-01-01T00:00:00%2B07:00
```

---

### `GET /api/ph-diagram/{compressor_id}` — ดึงข้อมูล P-H Diagram

**Query Parameters:**

| Parameter | Type | คำอธิบาย |
|-----------|------|----------|
| `record_id` | string | (optional) MongoDB `_id` ของ record ที่ต้องการ |
| `timestamp` | datetime | (optional) เวลาที่ต้องการ ±1 วินาที — ถ้าไม่ใส่ใช้ record ล่าสุด |

**Response:**

```json
{
  "compressor_id": "COMP-01",
  "timestamp": "2025-01-01T10:00:00+07:00",
  "record_id": "64abc...",
  "saturation_dome": {
    "liquid": [{ "h": 200.0, "p": 0.1000 }, "..."],
    "vapour": [{ "h": 1450.0, "p": 0.1000 }, "..."],
    "critical": { "h": 788.6, "p": 11.3328 }
  },
  "cycle": {
    "point1":  { "h": 1450.2, "p": 0.2370, "label": "1 — Comp. inlet", "t_c": -5.0 },
    "point2":  { "h": 1620.8, "p": 1.2800, "label": "2 — Comp. outlet", "t_c": 85.0 },
    "point2s": { "h": 1598.4, "p": 1.2800, "label": "2s — Isentropic" },
    "point3":  { "h": 325.1,  "p": 1.2800, "label": "3 — Cond. outlet", "t_c": 30.0 },
    "point4":  { "h": 325.1,  "p": 0.2370, "label": "4 — Evap. inlet" },
    "isentropic_efficiency": 0.8680
  }
}
```

**Cycle Points:**

```
1  → Compressor inlet  (suction, superheated vapour)
2  → Compressor outlet (discharge, actual)
2s → Isentropic discharge (ideal, for η_is)
3  → Condenser outlet  (liquid)
4  → Evaporator inlet  (after expansion valve, h4 = h3)
```

---

## Alarm Conditions

| Alarm | Severity | เงื่อนไข |
|-------|----------|---------|
| Low COP | Warning | COP < 1.5 |
| High Superheat | Warning | Superheat > 15 K |
| Low Superheat | Warning | Superheat < 2 K |
| High Condensing Temp | Critical | Approach Temp > 15 K |

---

## Calculation Notes

- **Pressure conversion:** `P (Pa) = P (kg/cm²g) × 98,066.5 + 101,325`
- **Power (3-phase):** `P = √3 × 385V × I × 0.86 (PF)`
- **COP:** `(h1 - h3) / (h2 - h1)`
- **Q_e:** `Power × COP`
- **Refrigerant reference state:** IIR (International Institute of Refrigeration)

---

## Database Schema (MongoDB)

Collection: `compressor_data_v2`

```json
{
  "_id": "ObjectId",
  "compressor_id": "COMP-01",
  "timestamp": "ISODate",
  "inputs_snapshot": { "...sensor inputs..." },
  "diagnosis": { "...analysis result..." }
}
```