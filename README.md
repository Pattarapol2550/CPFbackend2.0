# Ammonia Diagnostics API v2

> **Live API:** https://cpfbackend2-0.onrender.com

REST API สำหรับวิเคราะห์ประสิทธิภาพและวินิจฉัยปัญหาระบบทำความเย็นแอมโมเนีย (single-stage และ two-stage) พัฒนาด้วย **FastAPI + PostgreSQL + CoolProp**

รองรับการบันทึกข้อมูล sensor จาก compressor, คำนวณ thermodynamic KPIs, สร้าง P-H diagram, ระบบ alarm, JWT authentication และเครื่องมือคำนวณแบบ stateless

---

## Features

- คำนวณ **COP, Q_e, Power, m_dot** จากข้อมูล sensor จริง
- วิเคราะห์ **Superheat / Subcooling / Pressure Ratio / Isentropic Efficiency**
- สร้าง **P-H Diagram** พร้อม Saturation Dome และ Cycle Points (1→2→2s→3→4)
- ระบบ **Alarm** แจ้งเตือน เช่น Low COP, High/Low Superheat, High Condensing Temp
- รองรับ **ค่า assume อัตโนมัติ** เมื่อ sensor บางตัวไม่มีข้อมูล (SH = 5 K, η_is = 0.70)
- บันทึกและดึงประวัติข้อมูลจาก **PostgreSQL** (SQLAlchemy async)
- **JWT authentication** — register, login, role-based access (`user` / `admin`)
- **Calculator endpoints** — single-stage และ two-stage (ไม่ต้อง login, ไม่บันทึก DB)
- โครงสร้างแบบ **modular package** (`app/`) แยก routers, services, models, schemas

---

## Tech Stack

| Component | Library / Tool |
|-----------|----------------|
| Framework | FastAPI |
| Thermodynamics | CoolProp (Ammonia, IIR reference state) |
| Database | PostgreSQL via SQLAlchemy 2.x async + asyncpg |
| Authentication | PyJWT + bcrypt + HTTP Bearer |
| Validation | Pydantic v2 (`EmailStr`, `field_validator`) |
| Numerics | NumPy |
| Server | Uvicorn |
| Deployment | Render (`render.yaml`) |
| Testing | pytest + pytest-asyncio + pytest-cov + httpx |

---

## Project Structure

```
CPFbackend2.0/
├── main.py                  # Deployment shim — re-exports app for `uvicorn main:app`
├── test_main.py             # Unit & integration tests (100% coverage target)
├── requirements.txt         # Python dependencies
├── render.yaml              # Render.com deployment config
├── README.md
│
└── app/
    ├── main.py              # FastAPI factory (create_app), CORS, router registration, startup
    ├── config.py            # DATABASE_URL, JWT_SECRET, TOKEN_TTL from .env
    ├── database.py          # Async engine, session factory, get_db dependency
    │
    ├── core/
    │   ├── constants.py     # FLUID, TZ_TH, validation regex, electrical defaults
    │   └── security.py      # bcrypt, JWT, require_user / require_admin dependencies
    │
    ├── models/
    │   ├── user.py          # UserModel → table `users`
    │   └── metric.py        # MetricModel → table `compressor_data`
    │
    ├── schemas/
    │   ├── auth.py          # RegisterIn, LoginIn, AdminCreateUserIn
    │   ├── metrics.py       # CompressorDataInput
    │   └── calculator.py    # CalcInput, TwoStageInput
    │
    ├── routers/
    │   ├── auth.py          # /api/auth/*
    │   ├── metrics.py       # /api/metrics/*
    │   ├── ph_diagram.py    # /api/ph-diagram/*
    │   └── calculator.py    # /api/calculate, /api/calculate_two
    │
    └── services/
        ├── diagnostics.py   # diagnose_compressor() — core alarm + KPI logic
        ├── ph_diagram.py    # build_saturation_dome(), compute_cycle_points()
        ├── calculator.py    # calculate_single_stage(), calculate_two_stage()
        └── utils.py         # safe_round(), pressure_kgcm2_to_pa()
```

### Entry points

| Command | What runs |
|---------|-----------|
| `uvicorn main:app` | Root `main.py` shim → `app.main.app` (used in production / Render) |
| `python main.py` | Same app with `--reload` on port 8000 |
| `python -m app.main` | Alternative direct entry (also supported) |

---

## Architecture

```
Client (Frontend / IoT / Swagger)
        │
        ▼
┌───────────────────────────────────────┐
│  FastAPI (app/main.py)                │
│  ├── CORS middleware                  │
│  ├── auth router      → JWT + users   │
│  ├── metrics router   → diagnose + DB │
│  ├── ph_diagram router→ cycle + dome  │
│  └── calculator router→ stateless     │
└───────────────────────────────────────┘
        │                    │
        ▼                    ▼
   CoolProp / NumPy     PostgreSQL
   (thermo engine)      (users, compressor_data)
```

### Request flow — metrics (core domain)

1. Client sends `POST /api/metrics` with Bearer token
2. `diagnose_compressor()` runs CoolProp calculations and builds alarms
3. Record saved to `compressor_data` (inputs + diagnosis as JSON)
4. Analysis returned immediately

### Authentication flow

1. `POST /api/auth/register` or admin `POST /api/auth/admin/create-user`
2. `POST /api/auth/login` → returns JWT (8-hour TTL)
3. Protected routes require header: `Authorization: Bearer <token>`
4. Admin routes additionally require `role: admin` in the token

---

## Installation

```bash
# 1. Clone repo
git clone <repo-url>
cd CPFbackend2.0

# 2. Create virtual environment (recommended)
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install test dependencies (optional)
pip install pytest pytest-asyncio pytest-cov httpx anyio aiosqlite
```

### Environment variables

Create a `.env` file in the project root:

```env
# PostgreSQL — must use async driver prefix
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/ammonia_db

# JWT signing secret — use a long random string in production
JWT_SECRET=change-me-in-production-use-strong-secret
```

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | Async SQLAlchemy URL (`postgresql+asyncpg://...`) |
| `JWT_SECRET` | ✅ (prod) | HMAC secret for JWT; defaults to insecure placeholder if unset |

> Tables are created automatically on startup via `Base.metadata.create_all`. For production schema changes, consider adding Alembic migrations.

---

## Run Server

```bash
# Development (auto-reload)
python main.py

# Or explicitly
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

| URL | Description |
|-----|-------------|
| http://localhost:8000 | API root |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/redoc | ReDoc |

---

## Deployment (Render)

`render.yaml` configures:

- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Env vars:** `DATABASE_URL`, `JWT_SECRET` (set manually in Render dashboard)

---

## API Endpoints

### Authentication (`/api/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | — | Self-registration (`role=user`) |
| POST | `/api/auth/login` | — | Login by username or email → JWT |
| GET | `/api/auth/me` | User | Current user profile |
| POST | `/api/auth/admin/create-user` | Admin | Create user with chosen role |
| GET | `/api/auth/admin/users` | Admin | List users (max 500) |

#### `POST /api/auth/register`

**Request:**

```json
{
  "username": "operator1",
  "email": "op@example.com",
  "password": "SecurePass1",
  "phone": "0812345678"
}
```

**Validation rules:**

| Field | Rule |
|-------|------|
| `username` | 3–32 chars, `[a-zA-Z0-9_.]` only |
| `password` | 8–128 chars, at least 1 uppercase, 1 lowercase, 1 digit |
| `phone` | Thai mobile format, e.g. `0812345678` |

**Response (201):**

```json
{ "ok": true, "message": "สมัครสมาชิกสำเร็จ" }
```

#### `POST /api/auth/login`

**Request:**

```json
{
  "identifier": "operator1",
  "password": "SecurePass1"
}
```

`identifier` accepts **username or email** (case-insensitive).

**Response (200):**

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": { "username": "operator1", "role": "user" }
}
```

---

### Metrics (`/api/metrics`) — requires Bearer token

#### `POST /api/metrics` — บันทึกข้อมูลและวิเคราะห์

**Request:**

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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `compressor_id` | string | ✅ | รหัส Compressor |
| `sp_kg` | float | ✅ | Suction pressure (kg/cm²g) |
| `dp_kg` | float | ✅ | Discharge pressure (kg/cm²g) |
| `timestamp` | datetime | ❌ | ISO 8601 — default: now (UTC+7) |
| `st_c` | float | ❌ | Suction temperature (°C) — ถ้าไม่ใส่ assume SH = 5 K |
| `dt_c` | float | ❌ | Discharge temperature (°C) — ถ้าไม่ใส่ assume η_is = 0.70 |
| `liquid_temp_c` | float | ❌ | Liquid line temperature (°C) |
| `current_amp` | float | ❌ | Motor current (A) — ใช้คำนวณ power |
| `evaporator_room_temp_c` | float | ❌ | อุณหภูมิห้องเย็น (°C) |
| `condenser_temp_c` | float | ❌ | อุณหภูมิน้ำ/อากาศ condenser (°C) |

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
    "modes": { "sh_mode": "measured", "dt_mode": "measured" },
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

#### `GET /api/metrics/{compressor_id}` — ดึงประวัติ (raw)

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 2000 | จำนวน record สูงสุด |
| `start` | datetime | — | เริ่มช่วงเวลา (ISO 8601) |
| `end` | datetime | — | สิ้นสุดช่วงเวลา (ISO 8601) |

**Example:**

```
GET /api/metrics/COMP-01?limit=100&start=2025-01-01T00:00:00%2B07:00
Authorization: Bearer <token>
```

Returns an array of records with `_id`, `compressor_id`, `timestamp`, `inputs_snapshot`, `diagnosis`.

#### `GET /api/metrics/{compressor_id}/detail` — ดึงประวัติ (flat view)

Same query parameters as above (`limit` default **100**).

Returns structured rows grouped into `input`, `performance`, `enthalpy`, `status`, `alarms`, and `alarm_count` — optimized for dashboard tables.

---

### P-H Diagram (`/api/ph-diagram`) — requires Bearer token

#### `GET /api/ph-diagram/{compressor_id}`

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `record_id` | string | (optional) PostgreSQL integer ID of the record |
| `timestamp` | datetime | (optional) Match record within ±1 second — if omitted, uses latest |

**Response:**

```json
{
  "compressor_id": "COMP-01",
  "timestamp": "2025-01-01T10:00:00+07:00",
  "record_id": "42",
  "saturation_dome": {
    "liquid": [{ "h": 200.0, "p": 0.1000 }],
    "vapour": [{ "h": 1450.0, "p": 0.1000 }],
    "critical": { "h": 788.6, "p": 11.3328 }
  },
  "cycle": {
    "point1":  { "h": 1450.2, "p": 0.2370, "label": "1 — Comp. inlet",  "t_c": -5.0 },
    "point2":  { "h": 1620.8, "p": 1.2800, "label": "2 — Comp. outlet", "t_c": 85.0 },
    "point2s": { "h": 1598.4, "p": 1.2800, "label": "2s — Isentropic" },
    "point3":  { "h": 325.1,  "p": 1.2800, "label": "3 — Cond. outlet", "t_c": 30.0 },
    "point4":  { "h": 325.1,  "p": 0.2370, "label": "4 — Evap. inlet" },
    "isentropic_efficiency": 0.8680
  }
}
```

**Cycle points:**

```
1  → Compressor inlet   (suction, superheated vapour)
2  → Compressor outlet  (discharge, actual)
2s → Isentropic discharge (ideal, for η_is)
3  → Condenser outlet   (liquid)
4  → Evaporator inlet   (after expansion valve, h4 = h3)
```

---

### Calculator (`/api/calculate`) — no auth required

Stateless thermodynamic calculators. Results are **not persisted**.

#### `POST /api/calculate` — single-stage

**Request:**

```json
{
  "current": 50.0,
  "sp": 3.0,
  "dp": 13.0,
  "st": 3.0,
  "dt": 80.0,
  "liquid_temp": 35.0,
  "sh_default": 5.0,
  "eta_is": 0.70,
  "voltage": 385.0,
  "power_factor": 0.86
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `current` | — | Motor current (A) |
| `sp`, `dp` | — | Suction / discharge pressure (kg/cm²g) |
| `st`, `dt` | null | Suction / discharge temp (°C) — omit to assume |
| `liquid_temp` | null | Liquid line temp (°C) |
| `sh_default` | 5.0 | Assumed superheat (K) when `st` omitted |
| `eta_is` | 0.70 | Assumed isentropic efficiency when `dt` omitted |
| `voltage` | 385.0 | 3-phase voltage (V) |
| `power_factor` | 0.86 | Power factor |

**Response sections:** `modes`, `inputs`, `saturation`, `enthalpy`, `performance`, `warnings`

#### `POST /api/calculate_two` — two-stage (booster + high)

**Request:**

```json
{
  "i_booster": 30.0,
  "sp": 0.5,
  "st": -20.0,
  "dt_booster": 10.0,
  "t_int": -7.0,
  "i_high": 45.0,
  "dp": 13.0,
  "dt_high": 80.0,
  "liquid_temp": 35.0,
  "sh_default": 5.0,
  "eta_booster": 0.70,
  "eta_high": 0.70,
  "voltage": 385.0,
  "power_factor": 0.86
}
```

**Response sections:** `modes`, `pressures`, `saturation`, `enthalpy`, `performance`, `warnings`

---

## Alarm Conditions

| Alarm | Severity | Condition |
|-------|----------|-----------|
| Low COP | Warning | COP < 1.5 |
| High Superheat | Warning | Superheat > 15 K |
| Low Superheat | Warning | Superheat < 2 K |
| High Condensing Temp | Critical | Approach temp > 15 K |

Approach temp = saturation condensing temperature − `condenser_temp_c` (when both are available).

---

## Calculation Notes

| Quantity | Formula |
|----------|---------|
| Pressure conversion | `P (Pa) = P (kg/cm²g) × 98,066.5 + 101,325` |
| Power (3-phase) | `P = √3 × V × I × PF` (default V=385 V, PF=0.86) |
| COP | `(h1 − h3) / (h2 − h1)` |
| Q_e | `Power × COP` |
| Mass flow | `Q_e × 1000 / (h1 − h3)` → kg/h |
| Refrigerant | Ammonia, IIR reference state |

**Assumption modes** (returned in `modes`):

| Mode key | `measured` | `assumed` / `assumed_5K` / `assumed_eta07` |
|----------|------------|---------------------------------------------|
| `sh_mode` | `st_c` provided | default 5 K superheat |
| `dt_mode` | `dt_c` provided | η_is = 0.70 |
| `liq_mode` | `liquid_temp_c` provided | saturated liquid at discharge P |

---

## Database Schema (PostgreSQL)

Tables are created on startup. Timestamps are stored with timezone; API responses use **UTC+7 (Asia/Bangkok)**.

### Table: `users`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `username` | VARCHAR(32) UNIQUE | Display name |
| `username_lower` | VARCHAR(32) UNIQUE | Case-insensitive lookup |
| `email` | VARCHAR(255) UNIQUE | Stored lowercase |
| `phone` | VARCHAR(20) | Thai mobile |
| `password_hash` | VARCHAR(255) | bcrypt (12 rounds) |
| `role` | VARCHAR(20) | `user` or `admin` |
| `created_at` | TIMESTAMPTZ | UTC |
| `is_active` | VARCHAR(5) | `"true"` / suspended otherwise |

### Table: `compressor_data`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `compressor_id` | VARCHAR(100) INDEX | e.g. `COMP-01` |
| `timestamp` | TIMESTAMPTZ INDEX | Reading time (UTC+7 in API) |
| `inputs_snapshot` | JSONB | Raw sensor payload |
| `diagnosis` | JSONB | Full `diagnose_compressor()` output |

**Example row:**

```json
{
  "id": 42,
  "compressor_id": "COMP-01",
  "timestamp": "2025-01-01T10:00:00+07:00",
  "inputs_snapshot": { "sp_kg": 1.5, "dp_kg": 12.0, "st_c": -5.0 },
  "diagnosis": { "cop": 2.67, "alarms": [], "enthalpy": { "..." : "..." } }
}
```

---

## Testing

Tests live in `test_main.py` at the project root. They import via the root `main.py` shim (backward-compatible re-exports) and mock the database with in-memory SQLite + dependency overrides.

### Install test dependencies

```bash
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov httpx anyio aiosqlite
```

### Run tests

**Basic (pass/fail):**

```bash
python -m pytest test_main.py -v
```

**With coverage (recommended):**

```bash
python -m pytest test_main.py --cov=app --cov=main --cov-branch --cov-report=term-missing -v
```

**HTML coverage report:**

```bash
python -m pytest test_main.py --cov=app --cov=main --cov-branch --cov-report=term-missing --cov-report=html -v
# Open htmlcov/index.html in a browser
```

### Coverage targets

| Type | Goal |
|------|------|
| Statement coverage | Every line executed at least once |
| Branch coverage | Every if/else/try path covered |
| Path coverage | All `measured` vs `assumed` paths in diagnostics |

### Test groups

| Group | What is tested |
|-------|----------------|
| `TestSafeRound` | Formatting helper edge cases |
| `TestDiagnoseCompressor` | All diagnostic paths, alarms, assumptions |
| `TestComputeCyclePoints` | P-H cycle point computation |
| `TestBuildSaturationDome` | Dome structure and error recovery |
| HTTP `/api/metrics` | POST save, GET list, date filters (with auth mock) |
| HTTP `/api/ph-diagram` | Latest, by timestamp, by record_id, 404/400 |
| `TestDiagnoseExtraBranches` | Additional branch coverage for edge thermo paths |

HTTP tests use an `authed_client` fixture that overrides `require_user` and `get_db` — no real PostgreSQL connection required.

---

## HTTP Status Codes

| Code | Typical cause |
|------|---------------|
| 200 | Success |
| 201 | User registered / created |
| 400 | Invalid `record_id` on P-H diagram |
| 401 | Missing/invalid/expired JWT, wrong password |
| 403 | Account suspended, or non-admin on admin route |
| 404 | No compressor data found |
| 409 | Username or email already taken |
| 422 | Pydantic validation error (bad request body) |

---

## Creating the first admin user

There is no built-in bootstrap endpoint. Options:

1. Register a normal user, then update `role` to `admin` directly in PostgreSQL
2. Use an existing admin account to call `POST /api/auth/admin/create-user` with `"role": "admin"`

---

## License

Internal / project use — see repository owner for licensing terms.
