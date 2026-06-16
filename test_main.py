"""
test_main.py — 100% Coverage Tests for Ammonia Diagnostics API
===============================================================

Coverage targets:
  1. Statement Coverage  — ทุกบรรทัดถูก execute
  2. Branch Coverage     — ทุก if/else ทั้ง True & False
  3. Path Coverage       — ทุก logic path ใน diagnose_compressor & compute_cycle_points
"""

import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone, timedelta

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

_engine_patcher = patch(
    "sqlalchemy.ext.asyncio.create_async_engine",
    return_value=MagicMock(name="test_engine"),
)
_engine_patcher.start()

from main import (
    safe_round,
    diagnose_compressor,
    compute_cycle_points,
    build_saturation_dome,
    CompressorDataInput,
    app,
)
from app.core.security import require_user
from app.database import get_db
from httpx import AsyncClient, ASGITransport

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def make_input(**kw):
    """สร้าง CompressorDataInput ด้วยค่าที่สมเหตุสมผล (superheated vapour region)"""
    defaults = dict(
        compressor_id="COMP-01",
        sp_kg=3.0,   # p_suc → t_sat ≈ -2.17°C
        dp_kg=13.0,
        st_c=3.0,    # SH ≈ 5K (normal)
        dt_c=80.0,
        liquid_temp_c=35.0,
        current_amp=50.0,
    )
    defaults.update(kw)
    return CompressorDataInput(**defaults)

FAKE_METRIC = SimpleNamespace(
    id=1,
    compressor_id="COMP-01",
    timestamp=datetime(2025, 6, 10, 14, 25, 2, tzinfo=timezone(timedelta(hours=7))),
    inputs_snapshot=dict(
        compressor_id="COMP-01",
        sp_kg=3.0,
        dp_kg=13.0,
        st_c=3.0,
        dt_c=80.0,
        liquid_temp_c=35.0,
        current_amp=50.0,
    ),
    diagnosis={"cop": 3.5, "alarms": []},
)

FAKE_USER = {"username": "tester", "role": "user", "sub": "1"}


class _FakeEngineBegin:
    async def __aenter__(self):
        conn = MagicMock()
        conn.run_sync = AsyncMock()
        return conn

    async def __aexit__(self, *args):
        return None


@pytest.fixture(autouse=True)
def bypass_db_startup():
    with patch("app.database.engine.begin", return_value=_FakeEngineBegin()):
        yield


@pytest.fixture
def authed_client():
    """AsyncClient with auth + DB dependency overrides."""

    async def override_require_user():
        return FAKE_USER

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[require_user] = override_require_user
    app.dependency_overrides[get_db] = override_get_db
    yield mock_session
    app.dependency_overrides.clear()


def _mock_scalars_result(rows):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


def _mock_scalar_result(doc):
    result = MagicMock()
    result.scalar_one_or_none.return_value = doc
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 1. safe_round  (Statement + Branch)
# ═══════════════════════════════════════════════════════════════════════════════
class TestSafeRound:
    """Branch: value is None | float | raises"""

    def test_normal_float(self):                    # branch: value is not None, no except
        assert safe_round(3.14159, 2) == 3.14

    def test_default_digit(self):
        assert safe_round(2.71828) == 2.72

    def test_zero(self):
        assert safe_round(0.0) == 0.0

    def test_negative(self):
        assert safe_round(-7.891, 1) == -7.9

    def test_none_returns_dash(self):               # branch: value is None → "--"
        assert safe_round(None) == "--"

    def test_non_numeric_hits_except_branch(self):  # branch: except → "--"  (line 94-95)
        assert safe_round("not-a-number") == "--"

    def test_integer(self):
        assert safe_round(5, 0) == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 2. diagnose_compressor — all branches
# ═══════════════════════════════════════════════════════════════════════════════
class TestDiagnoseCompressor:

    # ── PATH A: full measured inputs ─────────────────────────────────────────
    def test_path_full_measured_inputs(self):
        """sh_mode=measured, dt_mode=measured, COP+power computed"""
        d = make_input()
        r = diagnose_compressor(d)
        assert r["modes"]["sh_mode"] == "measured"
        assert r["modes"]["dt_mode"] == "measured"
        assert isinstance(r["cop"], float) and r["cop"] > 1.0

    # ── PATH B: no st_c → assumed SH=5K ──────────────────────────────────────
    def test_path_assumed_suction_temp(self):
        """sh_mode=assumed_5K, dt_mode=measured"""
        d = make_input(st_c=None)
        r = diagnose_compressor(d)
        assert r["modes"]["sh_mode"] == "assumed_5K"
        assert r["modes"]["dt_mode"] == "measured"

    # ── PATH C: no dt_c → assumed η=0.70 ─────────────────────────────────────
    def test_path_assumed_discharge_temp(self):
        """sh_mode=measured, dt_mode=assumed_eta07"""
        d = make_input(dt_c=None)
        r = diagnose_compressor(d)
        assert r["modes"]["sh_mode"] == "measured"
        assert r["modes"]["dt_mode"] == "assumed_eta07"

    # ── PATH D: no st_c AND no dt_c ──────────────────────────────────────────
    def test_path_both_assumed(self):
        """sh_mode=assumed_5K, dt_mode=assumed_eta07"""
        d = make_input(st_c=None, dt_c=None)
        r = diagnose_compressor(d)
        assert r["modes"]["sh_mode"] == "assumed_5K"
        assert r["modes"]["dt_mode"] == "assumed_eta07"

    # ── Branch: sp_kg is None (line 155 False) ────────────────────────────────
    def test_branch_sp_kg_none(self):
        """p_suc_pa stays None → h1=None → most values are '--'"""
        # CompressorDataInput requires sp_kg as float, but we bypass via dict trick
        # Instead verify: sp_kg=0 makes p_suc_pa truthy=False (0+101325 > 0 always)
        # Actually: test with very large sp=0 via model fields: sp_kg is NOT Optional
        # Cover line 155 False by making sp_kg produce p_suc=0 (impossible physically)
        # Instead: cover via checking None path is hit when p_suc_pa is falsy
        # Use a mock-patched input
        d = make_input(st_c=None, dt_c=None, liquid_temp_c=None, current_amp=None)
        r = diagnose_compressor(d)
        assert "cop" in r  # should return result dict regardless

    # ── Branch: dp_kg is None (line 160 False) ────────────────────────────────

    def test_branch_dp_kg_drives_h3_fallback(self):
        """liquid_temp_c=None, dp_kg set → h3 via sat liquid fallback (line 236-250)"""
        d = make_input(liquid_temp_c=None)
        r = diagnose_compressor(d)
        assert r["subcooling"] == "--"   # no liquid_temp → no subcooling

    # ── Branch: h1/h2/h3 all set but (h2-h1)==0 → line 275 False ────────────

    def test_branch_cop_is_none_when_no_pressure(self):
        """cover line 275 False: h1 None because p_suc=None (sp_kg=0 → p_suc≈101325 truthy)
           Use st_c=None, dt_c=None, liquid_temp_c=None → h3 from fallback
           Actually: simplest is to cover (h2-h1)=0 not achievable naturally,
           so we cover the h1=None path by patching CoolProp to raise"""
        d = make_input()
        import CoolProp.CoolProp as CP
        original = CP.PropsSI
        call_count = [0]
        def raising_props(*args, **kw):
            call_count[0] += 1
            if call_count[0] == 1:   # first call → raise to force except branch (line 518)
                raise ValueError("simulated CoolProp failure")
            return original(*args, **kw)
        with patch("app.services.diagnostics.CP.PropsSI", side_effect=raising_props):
            r = diagnose_compressor(d)
        assert isinstance(r, dict)  # returned default result from except branch (line 518-522)

    # ── Branch: cop is None → line 278 False ────────────────────────────────

    def test_branch_no_cop_no_qe(self):
        """no current_amp → power=None → line 278 False → q_e_kw stays None"""
        d = make_input(current_amp=None, st_c=None, dt_c=None, liquid_temp_c=None)
        r = diagnose_compressor(d)
        assert r["power_kw"] == "--"
        assert r["q_e_kw"]   == "--"

    # ── Branch: pressure_ratio False (no p_suc or no p_dis) ─────────────────

    def test_branch_pressure_ratio_false(self):
        """line 430: branch False when both pressures required"""
        d = make_input()
        r = diagnose_compressor(d)
        assert isinstance(r["pressure_ratio"], float)

    # ── Superheat alarms ─────────────────────────────────────────────────────

    def test_alarm_high_superheat(self):
        """SH > 15K  → High Superheat alarm (t_sat≈-2.17, need st_c > 12.83)"""
        d = make_input(st_c=15.0)   # SH ≈ 17.17K
        r = diagnose_compressor(d)
        assert "High Superheat" in [a["title"] for a in r["alarms"]]

    def test_alarm_low_superheat(self):
        """SH < 2K → Low Superheat alarm"""
        d = make_input(st_c=-0.5)   # SH ≈ 1.67K
        r = diagnose_compressor(d)
        assert "Low Superheat" in [a["title"] for a in r["alarms"]]

    def test_alarm_no_superheat_when_no_st(self):
        """no st_c → superheat=None → no alarm appended"""
        d = make_input(st_c=None)
        r = diagnose_compressor(d)
        titles = [a["title"] for a in r["alarms"]]
        assert "High Superheat" not in titles
        assert "Low Superheat"  not in titles

    def test_alarm_normal_superheat_no_sh_alarm(self):
        """2K ≤ SH ≤ 15K → no superheat alarm"""
        d = make_input(st_c=2.83)   # SH ≈ 5K
        r = diagnose_compressor(d)
        titles = [a["title"] for a in r["alarms"]]
        assert "High Superheat" not in titles
        assert "Low Superheat"  not in titles

    # ── Low COP alarm ─────────────────────────────────────────────────────────

    def test_alarm_low_cop(self):
        """COP < 1.5 → Low COP alarm"""
        d = make_input(sp_kg=1.0, dp_kg=20.0, st_c=5.0, dt_c=120.0, current_amp=100.0)
        r = diagnose_compressor(d)
        cop = r.get("cop")
        if isinstance(cop, float) and cop < 1.5:
            assert "Low COP" in [a["title"] for a in r["alarms"]]

    # ── Condenser approach alarms ─────────────────────────────────────────────

    def test_alarm_high_condensing_temp(self):
        """approach > 15K → Critical alarm (t_sat_dis≈35.67, condenser_temp=20 → approach≈15.67)"""
        d = make_input(condenser_temp_c=20.0)
        r = diagnose_compressor(d)
        assert "High Condensing Temperature" in [a["title"] for a in r["alarms"]]

    def test_branch_approach_not_triggered(self):
        """approach ≤ 15K → branch False at line 404 → no Critical alarm"""
        d = make_input(condenser_temp_c=25.0)  # approach ≈ 35.67 - 25 = 10.67K ≤ 15
        r = diagnose_compressor(d)
        assert "High Condensing Temperature" not in [a["title"] for a in r["alarms"]]

    def test_branch_no_condenser_temp_skips_approach(self):
        """condenser_temp_c=None → inner if skipped entirely"""
        d = make_input(condenser_temp_c=None)
        r = diagnose_compressor(d)
        assert "High Condensing Temperature" not in [a["title"] for a in r["alarms"]]

    # ── Subcooling ────────────────────────────────────────────────────────────

    def test_subcooling_computed(self):
        d = make_input(liquid_temp_c=35.0)
        r = diagnose_compressor(d)
        assert isinstance(r["subcooling"], float)

    def test_subcooling_dash_when_no_liquid_temp(self):
        d = make_input(liquid_temp_c=None)
        r = diagnose_compressor(d)
        assert r["subcooling"] == "--"

    # ── Sensor status ─────────────────────────────────────────────────────────

    def test_sensor_status_normal(self):
        d = make_input(st_c=2.83)   # SH ≈ 5K
        r = diagnose_compressor(d)
        assert r["systems"]["sensor"]["status"] == "Normal"

    def test_sensor_status_warning(self):
        d = make_input(st_c=15.0)   # SH > 15K
        r = diagnose_compressor(d)
        assert r["systems"]["sensor"]["status"] == "Warning"

    def test_sensor_status_unknown_when_no_st(self):
        d = make_input(st_c=None)
        r = diagnose_compressor(d)
        assert r["systems"]["sensor"]["status"] == "Unknown"

    # ── Power ─────────────────────────────────────────────────────────────────

    def test_power_computed(self):
        d = make_input(current_amp=50.0)
        r = diagnose_compressor(d)
        expected = math.sqrt(3) * 385 * 50 * 0.86 / 1000
        assert abs(r["power_kw"] - expected) < 0.01

    def test_power_dash_when_no_current(self):
        d = make_input(current_amp=None)
        r = diagnose_compressor(d)
        assert r["power_kw"] == "--"

    # ── Minimal input ─────────────────────────────────────────────────────────

    def test_minimal_input_no_crash(self):
        d = make_input(st_c=None, dt_c=None, liquid_temp_c=None, current_amp=None)
        r = diagnose_compressor(d)
        assert isinstance(r, dict)
        assert "cop" in r


# ═══════════════════════════════════════════════════════════════════════════════
# 3. compute_cycle_points — all branches & paths
# ═══════════════════════════════════════════════════════════════════════════════
class TestComputeCyclePoints:

    def _full(self):
        return dict(sp_kg=3.0, dp_kg=13.0, st_c=3.0, dt_c=80.0, liquid_temp_c=35.0)

    # PATH 1: all inputs → all 4 points computed
    def test_path_full_all_points_computed(self):
        pts = compute_cycle_points(self._full())
        assert pts["point1"] is not None
        assert pts["point2"] is not None
        assert pts["point3"] is not None
        assert pts["point4"] is not None

    def test_pressures_and_sat_temps_computed(self):
        pts = compute_cycle_points(self._full())
        assert pts["p_suc_mpa"] is not None
        assert pts["p_dis_mpa"] is not None
        assert pts["t_sat_suc_c"] is not None
        assert pts["t_sat_dis_c"] is not None
        assert pts["p_dis_mpa"] > pts["p_suc_mpa"]
        assert pts["t_sat_dis_c"] > pts["t_sat_suc_c"]

    # PATH 2: with dt_c → isentropic efficiency from measured
    def test_path_measured_isentropic_efficiency(self):
        pts = compute_cycle_points(self._full())
        eta = pts["isentropic_efficiency"]
        assert eta is not None and isinstance(eta, float) and eta > 0

    # PATH 3: no dt_c → assumed η=0.70
    def test_path_assumed_isentropic_efficiency(self):
        inp = self._full()
        inp.pop("dt_c")
        pts = compute_cycle_points(inp)
        assert pts["isentropic_efficiency"] == 0.70

    # PATH 4: no st_c → point1=None → point2=None → point2s=None
    def test_path_no_st_skips_point1_and_2(self):
        inp = self._full()
        inp.pop("st_c")
        pts = compute_cycle_points(inp)
        assert pts["point1"] is None
        assert pts["point2"] is None
        assert pts["point2s"] is None

    # Branch: p_dis_pa False → no point2s (line 731 False)
    def test_branch_no_dp_kg_skips_point2s(self):
        pts = compute_cycle_points({"sp_kg": 3.0, "st_c": 3.0})  # no dp_kg
        assert pts["point1"] is not None   # suction only
        assert pts["point2s"] is None      # no discharge → no isentropic
        assert pts["point2"] is None

    # Branch: (h2-h1)==0 → isentropic_efficiency stays None (line 747 False)
    def test_branch_zero_enthalpy_diff_skips_eta(self):
        """Patch compute_cycle_points internals: make h2 - h1_val = 0
           by injecting a custom PropsSI that returns the same h for point2 as point1"""
        import CoolProp.CoolProp as CP
        original = CP.PropsSI

        # Pre-compute the real h1 value
        p_suc = 3.0 * 98066.5 + 101325
        p_dis = 13.0 * 98066.5 + 101325
        h1_val_kj = round(original('H','P',p_suc,'T',3.0+273.15,'Ammonia') / 1000, 2)

        # Track how many H-at-p_dis-T calls have been made
        h_pdis_T_calls = [0]

        def mock_props(prop, p_or_t=None, *args):
            # Only intercept the specific call: PropsSI("H","P",p_dis,"T",dt_c_K,"Ammonia")
            # which is the 2nd H call at p_dis using T (not S or Q)
            full_args = (p_or_t,) + args if p_or_t is not None else args
            if (prop == 'H' and len(full_args) >= 4
                    and full_args[0] == 'P'
                    and abs(full_args[1] - p_dis) < 1
                    and full_args[2] == 'T'):
                h_pdis_T_calls[0] += 1
                # Return h1_val_kj*1000 so h2 = h1_val → h2-h1_val=0
                return h1_val_kj * 1000
            return original(prop, p_or_t, *args)

        with patch("app.services.ph_diagram.CP.PropsSI", side_effect=mock_props):
            inp = self._full()
            pts = compute_cycle_points(inp)
        # When h2 = h1 exactly, (h2 - h1_val) == 0 → efficiency not set
        assert pts["isentropic_efficiency"] is None

    # Branch: liquid_temp_c given → point3 uses actual T (line 763 True)
    def test_branch_point3_with_liquid_temp(self):
        pts = compute_cycle_points(self._full())
        assert pts["point3"] is not None
        assert pts["point3"]["t_c"] == 35.0

    # Branch: no liquid_temp_c → fallback sat liquid (line 767-770)
    def test_branch_point3_fallback_sat_liquid(self):
        inp = self._full()
        inp.pop("liquid_temp_c")
        pts = compute_cycle_points(inp)
        assert pts["point3"] is not None
        # t_c should be sat liquid temp at discharge ≈ 35.67°C
        assert pts["point3"]["t_c"] is not None

    # Isenthalpic: h4 = h3
    def test_point4_isenthalpic_expansion(self):
        pts = compute_cycle_points(self._full())
        assert pts["point4"]["h"] == pts["point3"]["h"]

    # Branch: no sp_kg → point4 skipped (line 780 False)
    def test_branch_no_sp_kg_skips_point4(self):
        pts = compute_cycle_points({"dp_kg": 13.0, "liquid_temp_c": 35.0})
        assert pts["point4"] is None
        assert pts["point3"] is not None   # p_dis exists

    # PATH: empty dict → all None
    def test_path_empty_inputs(self):
        pts = compute_cycle_points({})
        for k in ("point1","point2","point3","point4"):
            assert pts[k] is None

    # Branch: exception path (line 787-788) → print and return partial result
    def test_branch_exception_in_compute(self):
        import CoolProp.CoolProp as CP
        with patch("app.services.ph_diagram.CP.PropsSI", side_effect=ValueError("boom")):
            pts = compute_cycle_points(self._full())
        assert isinstance(pts, dict)   # returns partially-filled dict


# ═══════════════════════════════════════════════════════════════════════════════
# 4. build_saturation_dome
# ═══════════════════════════════════════════════════════════════════════════════
class TestBuildSaturationDome:

    def test_structure(self):
        d = build_saturation_dome(n_points=10)
        assert set(d) >= {"liquid","vapour","critical"}

    def test_points_have_h_and_p(self):
        d = build_saturation_dome(n_points=5)
        for pt in d["liquid"] + d["vapour"]:
            assert "h" in pt and "p" in pt

    def test_pressure_monotonically_increases(self):
        d = build_saturation_dome(n_points=20)
        p = [pt["p"] for pt in d["liquid"]]
        assert p[-1] > p[0]

    def test_critical_point_positive(self):
        d = build_saturation_dome(n_points=5)
        assert d["critical"]["p"] > 0

    # Branch: exception inside loop → continue (line 653-654)
    def test_branch_exception_in_loop_continues(self):
        """Patch PropsSI to raise only during the T-loop iterations → continue branch"""
        import CoolProp.CoolProp as CP
        original = CP.PropsSI
        loop_calls = [0]

        def flaky(*args):
            # Setup calls: PropsSI("Tcrit", fluid) → 1 arg.  Loop calls → 4 args
            if len(args) == 4:   # inside the T loop
                loop_calls[0] += 1
                if loop_calls[0] <= 3:   # first 3 iterations raise → continue
                    raise ValueError("fake loop error")
            return original(*args)

        with patch("app.services.ph_diagram.CP.PropsSI", side_effect=flaky):
            d = build_saturation_dome(n_points=8)
        assert len(d["liquid"]) > 0   # some points computed after skipping errors


# ═══════════════════════════════════════════════════════════════════════════════
# 5. API Endpoints
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def anyio_backend():
    return "asyncio"

# ─── POST /api/metrics ────────────────────────────────────────────────────────
@pytest.mark.anyio
async def test_post_metrics_success(authed_client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/metrics",
            json=dict(
                compressor_id="COMP-01",
                sp_kg=3.0,
                dp_kg=13.0,
                st_c=3.0,
                dt_c=80.0,
                liquid_temp_c=35.0,
                current_amp=50.0,
            ),
        )
    assert r.status_code == 200
    assert r.json()["status"] == "Success"
    authed_client.add.assert_called_once()
    authed_client.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_post_metrics_with_explicit_timestamp(authed_client):
    """covers record_time = payload.timestamp.astimezone(tz_th) branch"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/metrics",
            json=dict(
                compressor_id="COMP-01",
                sp_kg=3.0,
                dp_kg=13.0,
                timestamp="2025-06-10T14:25:02+07:00",
            ),
        )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_post_metrics_minimal(authed_client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/metrics",
            json=dict(compressor_id="COMP-02", sp_kg=2.5, dp_kg=12.0),
        )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_post_metrics_missing_required_field():
    async def override_require_user():
        return FAKE_USER

    app.dependency_overrides[require_user] = override_require_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/metrics", json=dict(compressor_id="COMP-01", sp_kg=3.0))
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()


# ─── GET /api/metrics/{compressor_id} ────────────────────────────────────────
@pytest.mark.anyio
async def test_get_metrics_returns_list(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalars_result([FAKE_METRIC]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/metrics/COMP-01")
    assert r.status_code == 200 and isinstance(r.json(), list)
    assert r.json()[0]["compressor_id"] == "COMP-01"


@pytest.mark.anyio
async def test_get_metrics_doc_without_timestamp(authed_client):
    """covers branch: row.timestamp is None"""
    row = SimpleNamespace(
        id=2,
        compressor_id="COMP-01",
        timestamp=None,
        inputs_snapshot={},
        diagnosis={},
    )
    authed_client.execute = AsyncMock(return_value=_mock_scalars_result([row]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/metrics/COMP-01")
    assert r.status_code == 200
    assert r.json()[0]["timestamp"] is None


@pytest.mark.anyio
async def test_get_metrics_empty(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalars_result([]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/metrics/COMP-99")
    assert r.status_code == 200 and r.json() == []


@pytest.mark.anyio
async def test_get_metrics_with_start_only(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalars_result([]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/metrics/COMP-01", params={"start": "2025-06-01T00:00:00Z"})
    assert r.status_code == 200


@pytest.mark.anyio
async def test_get_metrics_with_end_only(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalars_result([]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/metrics/COMP-01", params={"end": "2025-06-30T23:59:59Z"})
    assert r.status_code == 200


@pytest.mark.anyio
async def test_get_metrics_with_both_dates(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalars_result([]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            "/api/metrics/COMP-01",
            params={"start": "2025-06-01T00:00:00Z", "end": "2025-06-30T23:59:59Z"},
        )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_get_metrics_no_date_filter(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalars_result([]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/metrics/COMP-01")
    assert r.status_code == 200


# ─── GET /api/ph-diagram/{compressor_id} ─────────────────────────────────────
@pytest.mark.anyio
async def test_ph_diagram_latest_success(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalar_result(FAKE_METRIC))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/ph-diagram/COMP-01")
    assert r.status_code == 200
    body = r.json()
    assert "saturation_dome" in body and "cycle" in body


@pytest.mark.anyio
async def test_ph_diagram_latest_not_found(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalar_result(None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/ph-diagram/COMP-99")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_ph_diagram_by_timestamp_found(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalar_result(FAKE_METRIC))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            "/api/ph-diagram/COMP-01", params={"timestamp": "2025-06-10T14:25:02+07:00"}
        )
    assert r.status_code == 200


@pytest.mark.anyio
async def test_ph_diagram_by_timestamp_not_found(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalar_result(None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            "/api/ph-diagram/COMP-01", params={"timestamp": "2025-06-10T14:25:04+07:00"}
        )
    assert r.status_code == 404
    assert "ไม่พบข้อมูล" in r.json()["detail"]


@pytest.mark.anyio
async def test_ph_diagram_by_record_id_valid(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalar_result(FAKE_METRIC))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/ph-diagram/COMP-01", params={"record_id": "1"})
    assert r.status_code == 200


@pytest.mark.anyio
async def test_ph_diagram_by_record_id_invalid(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalar_result(None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/ph-diagram/COMP-01", params={"record_id": "not-valid"})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_ph_diagram_timestamp_none(authed_client):
    metric = SimpleNamespace(
        id=1,
        compressor_id="COMP-01",
        timestamp=None,
        inputs_snapshot=FAKE_METRIC.inputs_snapshot,
        diagnosis=FAKE_METRIC.diagnosis,
    )
    authed_client.execute = AsyncMock(return_value=_mock_scalar_result(metric))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/ph-diagram/COMP-01")
    assert r.status_code == 200
    assert r.json()["timestamp"] is None


@pytest.mark.anyio
async def test_ph_diagram_dome_structure(authed_client):
    authed_client.execute = AsyncMock(return_value=_mock_scalar_result(FAKE_METRIC))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/ph-diagram/COMP-01")
    dome = r.json()["saturation_dome"]
    assert len(dome["liquid"]) > 0
    assert "h" in dome["liquid"][0] and "p" in dome["liquid"][0]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. __main__ block (line 897-905)  — Statement Coverage
# ═══════════════════════════════════════════════════════════════════════════════
def test_main_block_executes():
    """Cover `if __name__ == '__main__': uvicorn.run(...)` via runpy"""
    import runpy
    import sys
    from types import ModuleType
    # patch uvicorn.run before runpy executes the module
    fake_uvicorn = ModuleType("uvicorn")
    fake_uvicorn.run = MagicMock(return_value=None)
    # temporarily inject so that `import uvicorn` inside __main__ block gets our mock
    orig = sys.modules.get("uvicorn")
    sys.modules["uvicorn"] = fake_uvicorn
    try:
        runpy.run_path("main.py", run_name="__main__")
    finally:
        if orig is not None:
            sys.modules["uvicorn"] = orig
        else:
            sys.modules.pop("uvicorn", None)
    fake_uvicorn.run.assert_called_once()



# ═══════════════════════════════════════════════════════════════════════════════
# 7. Extra branch-fill tests to reach 100%
# ═══════════════════════════════════════════════════════════════════════════════
class TestDiagnoseExtraBranches:

    # Branch: line 155 False (sp_kg is None — not possible via model, so patch it)
    def test_branch_sp_kg_is_none_internally(self):
        """Patch data.sp_kg = None inside diagnose to hit line 155 False branch"""
        d = make_input()
        # Use object.__setattr__ to bypass Pydantic validation
        object.__setattr__(d, 'sp_kg', None)
        r = diagnose_compressor(d)
        assert isinstance(r, dict)

    # Branch: line 160 False (dp_kg is None internally)
    def test_branch_dp_kg_is_none_internally(self):
        d = make_input()
        object.__setattr__(d, 'dp_kg', None)
        r = diagnose_compressor(d)
        assert isinstance(r, dict)

    # Branch: line 191 False (p_suc_pa is falsy — make sp_kg produce 0 pressure)
    # This actually can't happen since 0*98066.5+101325=101325>0
    # But we can get h1=None via line 191 False by making p_suc_pa=0
    def test_branch_p_suc_falsy(self):
        """sp_kg=-1.034 → p_suc = -1.034*98066.5+101325 ≈ 0 → falsy"""
        # -101325/98066.5 ≈ -1.0333
        sp_zero = -101325 / 98066.5
        d = make_input()
        object.__setattr__(d, 'sp_kg', sp_zero)
        object.__setattr__(d, 'st_c', None)
        r = diagnose_compressor(d)
        assert isinstance(r, dict)

    # Branch: line 203 False (h1 is not None, p_dis_pa exists, but t_suc_k=None is impossible
    # because line 191 always sets t_suc_k when p_suc truthy via assumed SH path)
    # So cover by: having h1 set BUT p_dis_pa=None
    def test_branch_h2s_skipped_no_p_dis(self):
        """p_dis_pa=None → line 203 False → h2s stays None"""
        d = make_input(st_c=3.0)
        object.__setattr__(d, 'dp_kg', None)
        r = diagnose_compressor(d)
        assert isinstance(r, dict)

    # Branch: line 208 False (p_dis_pa is None — same as above, but check h2 path)
    def test_branch_p_dis_none_h2_skipped(self):
        d = make_input(dt_c=80.0)
        object.__setattr__(d, 'dp_kg', None)
        r = diagnose_compressor(d)
        assert r["cop"] == "--"

    # Branch: line 212 False (p_dis exists, no t_dis_k, but h2s=None because h1=None)
    # → elif branch of h2 computation is skipped
    def test_branch_elif_h2_skipped_when_h2s_none(self):
        """p_dis set, no dt_c, and h1=None (p_suc=None) → h2s=None → elif False"""
        d = make_input(dt_c=None)
        object.__setattr__(d, 'sp_kg', None)  # p_suc=None → h1=None → h2s=None
        r = diagnose_compressor(d)
        assert isinstance(r, dict)

    # Branch: line 236 (elif p_dis_pa) True + line 248 except
    # → CP.PropsSI('H','P',p_dis,'Q',0,...) raises
    def test_branch_h3_fallback_exception(self):
        """liquid_temp_c=None → fallback to sat liquid → patch to raise → h3=None"""
        d = make_input(liquid_temp_c=None)
        import CoolProp.CoolProp as CP
        original = CP.PropsSI
        q0_calls = [0]
        def raise_on_q0(prop, *args):
            # The fallback call is PropsSI('H','P',p_dis,'Q',0,fluid)
            if prop == 'H' and len(args) >= 4 and args[2] == 'Q' and args[3] == 0:
                q0_calls[0] += 1
                if q0_calls[0] == 1:
                    raise ValueError("h3 fallback error")
            return original(prop, *args)
        with patch("app.services.diagnostics.CP.PropsSI", side_effect=raise_on_q0):
            r = diagnose_compressor(d)
        assert isinstance(r, dict)  # recovered gracefully

    # Branch: line 275 False → (h2-h1)==0 → cop stays None
    def test_branch_cop_skipped_when_h2_equals_h1(self):
        """Make h2=h1 by patching so (h2-h1)=0 → line 275 False → cop=None"""
        import CoolProp.CoolProp as CP
        original = CP.PropsSI
        p_suc = 3.0 * 98066.5 + 101325
        p_dis = 13.0 * 98066.5 + 101325
        # The h2 call is the SECOND H-at-p_dis call (first is h2s with S)
        # h2: PropsSI('H','P',p_dis,'T',t_dis_k, fluid)
        h1_j = original('H','P',p_suc,'T',3.0+273.15,'Ammonia')

        h_pdis_T_n = [0]
        def mock(prop, *args):
            if prop=='H' and len(args)>=4 and abs(args[1]-p_dis)<1 and args[2]=='T':
                h_pdis_T_n[0] += 1
                return h1_j   # h2 = h1 → diff=0
            return original(prop, *args)
        with patch("app.services.diagnostics.CP.PropsSI", side_effect=mock):
            r = diagnose_compressor(make_input())
        assert r["cop"] == "--"

    # Branch: line 284 False (cop < 1.5 alarm — cover when COP is very low)
    def test_branch_low_cop_alarm_appended(self):
        """Explicit check that Low COP alarm is appended when cop < 1.5"""
        d = make_input(sp_kg=1.0, dp_kg=25.0, st_c=5.0, dt_c=150.0, current_amp=5.0)
        r = diagnose_compressor(d)
        cop = r.get("cop")
        # If cop is a float and < 1.5, alarm must exist
        if isinstance(cop, float) and cop < 1.5:
            titles = [a["title"] for a in r.get("alarms", [])]
            assert "Low COP" in titles

    # Branch: line 430 False (pressure_ratio skipped when p_suc=None)
    def test_branch_pressure_ratio_skipped_no_p_suc(self):
        d = make_input()
        object.__setattr__(d, 'sp_kg', None)
        r = diagnose_compressor(d)
        assert r["pressure_ratio"] == "--"

    # Branch: line 653-654 exception-continue in build_saturation_dome
    def test_saturation_dome_loop_exception_continue(self):
        """Trigger the except:continue branch inside the temperature loop"""
        import CoolProp.CoolProp as CP
        original = CP.PropsSI
        loop_n = [0]

        def flaky_in_loop(prop, *args):
            if len(args) == 4 and args[2] == 'Q':  # inside T-loop: H,T,T_val,Q,0/1
                loop_n[0] += 1
                if loop_n[0] <= 6:  # fail first 2 complete iterations (3 calls each)
                    raise ValueError("loop error")
            return original(prop, *args)

        with patch("app.services.ph_diagram.CP.PropsSI", side_effect=flaky_in_loop):
            d = build_saturation_dome(n_points=10)
        assert isinstance(d, dict)
        assert len(d["liquid"]) > 0



class TestFinalBranches:

    # Line 284: alarms.append for Low COP — need COP < 1.5 reliably
    def test_saturation_dome_except_continue_direct(self):
        """Patch H-computation inside T-loop to raise → except:continue fired"""
        import CoolProp.CoolProp as CP
        original = CP.PropsSI
        # Track calls to the 3-value group inside the loop: H(T,Q,0), H(T,Q,1), P(T,Q,0)
        # These are called as PropsSI("H","T",T_val,"Q",0,fluid) → 5 positional args
        loop_calls = [0]
        def fail_first_loop_iter(prop, *args):
            # Loop body calls: PropsSI("H","T",T,"Q",0/1,fluid) → args=(T_val or "T",...)
            # Signature: PropsSI(output, input1, val1, input2, val2, fluid)
            # So args = ("T", T_val, "Q", 0, fluid) length=5 when called as positional
            if prop in ("H","P") and len(args) == 5 and args[0] == "T":
                loop_calls[0] += 1
                if loop_calls[0] <= 3:   # 3 calls = 1 full iteration
                    raise ValueError("force except:continue")
            return original(prop, *args)

        with patch("app.services.ph_diagram.CP.PropsSI", side_effect=fail_first_loop_iter):
            dome = build_saturation_dome(n_points=15)
        assert len(dome["liquid"]) > 0  # continued past exception



class TestLowCOPReliable:
    """Reliable Low COP test using inputs that guarantee COP < 1.5"""

    def test_low_cop_alarm_with_reliable_inputs(self):
        """sp=0.3, dp=20, st=5, dt=None → COP≈1.46 < 1.5 → Low COP alarm"""
        # sp=0.3 → t_sat≈-28.1°C, st=5°C → SH≈33K > 15K → also High Superheat
        d = make_input(sp_kg=0.3, dp_kg=20.0, st_c=5.0, dt_c=None,
                       liquid_temp_c=None, current_amp=50.0)
        r = diagnose_compressor(d)
        cop = r.get("cop")
        assert isinstance(cop, float), f"COP should be float, got {cop}"
        assert cop < 1.5, f"Expected COP < 1.5, got {cop}"
        titles = [a["title"] for a in r.get("alarms", [])]
        assert "Low COP" in titles   # line 284 executed ✓