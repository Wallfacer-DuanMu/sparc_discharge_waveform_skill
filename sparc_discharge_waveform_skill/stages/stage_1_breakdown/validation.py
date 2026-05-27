"""Breakdown 阶段验证。

验证只做本阶段最小闭环需要的检查：输入结构、时间轴、线圈限幅、变化率、
CS 伏秒、零场质量、种子电流和波形连续性。
"""

from __future__ import annotations

from typing import Any


REQUIRED_TOP_LEVEL = ("case_name", "device", "timeline", "target", "coils", "constraints", "options")
DYNAMIC_COILS = ("CS1", "CS2", "CS3", "PF1", "PF2", "PF3", "PF4", "Div1", "Div2")
ALL_COILS = DYNAMIC_COILS + ("VS",)


def validate_config(config: dict[str, Any]) -> None:
    """验证输入配置是否满足 Breakdown 计算的基本要求。"""

    for key in REQUIRED_TOP_LEVEL:
        if key not in config:
            raise ValueError(f"missing required top-level field: {key}")

    timeline = config["timeline"]
    t_start = float(timeline["t_start_s"])
    t_end = float(timeline["breakdown_end_s"])
    dt = float(timeline["dt_s"])
    if t_end <= t_start:
        raise ValueError("timeline must satisfy t_start_s < breakdown_end_s")
    if dt <= 0:
        raise ValueError("timeline.dt_s must be greater than 0")
    if dt > t_end - t_start:
        raise ValueError("timeline.dt_s should not be greater than breakdown duration")

    target = config["target"]
    if float(target["Ip_seed_MA"]) < 0:
        raise ValueError("target.Ip_seed_MA must be non-negative")
    if "Ip_flat_MA" in target and float(target["Ip_flat_MA"]) <= float(target["Ip_seed_MA"]):
        raise ValueError("target.Ip_flat_MA should be greater than target.Ip_seed_MA")

    coils = config["coils"]
    for name in ALL_COILS:
        if name not in coils:
            raise ValueError(f"missing coil config: {name}")
        _validate_single_coil_config(name, coils[name], require_rate=name in DYNAMIC_COILS)

    constraints = config["constraints"]
    if float(constraints["breakdown_loop_voltage_V"]) <= 0:
        raise ValueError("constraints.breakdown_loop_voltage_V must be greater than 0")
    if float(constraints["cs_flux_budget_Vs"]) <= 0:
        raise ValueError("constraints.cs_flux_budget_Vs must be greater than 0")
    if float(constraints["breakdown_zero_field_tolerance_T"]) <= 0:
        raise ValueError("constraints.breakdown_zero_field_tolerance_T must be greater than 0")


def validate_breakdown_result(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    cs_flux_used_breakdown_vs: float,
    zero_field_error_t: float,
    physics_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回 Breakdown 结果验证报告。"""

    checks: list[dict[str, Any]] = []
    checks.append(_check_time_axis(config, rows))
    checks.extend(_check_current_limits(config, rows))
    checks.extend(_check_rate_limits(config, rows))
    checks.append(_check_cs_flux(config, cs_flux_used_breakdown_vs))
    checks.append(_check_zero_field(config, zero_field_error_t))
    checks.append(_check_seed_current(config, rows))
    checks.append(_check_continuity(rows))
    if physics_diagnostics:
        checks.extend(_check_physics_consistency(config, physics_diagnostics))

    issues = [check for check in checks if not check["passed"]]
    return {
        "passed": len(issues) == 0,
        "checks": checks,
        "issues": issues,
    }


def _validate_single_coil_config(name: str, coil: dict[str, Any], require_rate: bool) -> None:
    for key in ("I0_MA", "I_min_MA", "I_max_MA"):
        if key not in coil:
            raise ValueError(f"missing {name}.{key}")

    i0 = float(coil["I0_MA"])
    i_min = float(coil["I_min_MA"])
    i_max = float(coil["I_max_MA"])
    if i_min > i_max:
        raise ValueError(f"{name}.I_min_MA must not be greater than I_max_MA")
    if not i_min <= i0 <= i_max:
        raise ValueError(f"{name}.I0_MA must be within [I_min_MA, I_max_MA]")

    if require_rate:
        if "dI_dt_max_MA_per_s" not in coil:
            raise ValueError(f"missing {name}.dI_dt_max_MA_per_s")
        if float(coil["dI_dt_max_MA_per_s"]) <= 0:
            raise ValueError(f"{name}.dI_dt_max_MA_per_s must be greater than 0")
    elif name == "VS" and "reserved_fraction" not in coil:
        raise ValueError("VS.reserved_fraction is required")


def _check_time_axis(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    timeline = config["timeline"]
    t_start = float(timeline["t_start_s"])
    t_end = float(timeline["breakdown_end_s"])
    times = [float(row["time_s"]) for row in rows]
    passed = bool(times) and abs(times[0] - t_start) < 1e-9 and abs(times[-1] - t_end) < 1e-9
    passed = passed and all(t2 > t1 for t1, t2 in zip(times, times[1:]))
    return _check("time_axis", passed, "修正 timeline，保证起止时间正确且时间单调递增。")


def _check_current_limits(config: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    for coil_name in ALL_COILS:
        field = _field_name(coil_name)
        coil = config["coils"][coil_name]
        i_min = float(coil["I_min_MA"])
        i_max = float(coil["I_max_MA"])
        passed = all(i_min <= float(row[field]) <= i_max for row in rows)
        checks.append(_check(f"{coil_name}_current_limit", passed, f"调整 {coil_name} 目标电流或放宽限幅。"))
    return checks


def _check_rate_limits(config: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    for coil_name in DYNAMIC_COILS:
        field = _field_name(coil_name)
        rate_limit = float(config["coils"][coil_name]["dI_dt_max_MA_per_s"])
        passed = True
        for previous, current in zip(rows, rows[1:]):
            dt = float(current["time_s"]) - float(previous["time_s"])
            if dt <= 0:
                passed = False
                break
            rate = abs(float(current[field]) - float(previous[field])) / dt
            if rate > rate_limit + 1e-9:
                passed = False
                break
        checks.append(_check(f"{coil_name}_rate_limit", passed, f"延长 Breakdown 时间或降低 {coil_name} 变化幅度。"))
    return checks


def _check_cs_flux(config: dict[str, Any], used_vs: float) -> dict[str, Any]:
    constraints = config["constraints"]
    budget = float(constraints["cs_flux_budget_Vs"])
    margin_fraction = float(constraints.get("min_cs_flux_margin_fraction", 0.0))
    remaining = budget - used_vs
    passed = used_vs <= budget and remaining >= budget * margin_fraction
    return _check("cs_flux_margin", passed, "降低击穿电压、缩短击穿消耗，或提高 CS 伏秒预算。")


def _check_zero_field(config: dict[str, Any], error_t: float) -> dict[str, Any]:
    tolerance = float(config["constraints"]["breakdown_zero_field_tolerance_T"])
    passed = error_t <= tolerance
    return _check("zero_field_quality", passed, "优先调整 PF4，再调整 PF3，最后微调 PF1/PF2。")


def _check_seed_current(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    target = float(config["target"]["Ip_seed_MA"])
    actual = float(rows[-1]["Ip_MA"])
    tolerance = max(0.01, 0.05 * max(target, 1e-9))
    passed = abs(actual - target) <= tolerance
    return _check("seed_current", passed, "提高 loop voltage 或延长 Breakdown 时间。")


def _check_continuity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_fields = [key for key, value in rows[0].items() if isinstance(value, (int, float)) and key != "time_s"]
    passed = True
    for previous, current in zip(rows, rows[1:]):
        for field in numeric_fields:
            if abs(float(current[field]) - float(previous[field])) > 5.0:
                passed = False
                break
        if not passed:
            break
    return _check("waveform_continuity", passed, "使用更平滑的过渡函数或增加时间分辨率。")


def _check_physics_consistency(config: dict[str, Any], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    target_loop_voltage = float(config["constraints"]["breakdown_loop_voltage_V"])
    tolerance_fraction = float(config.get("physics", {}).get("loop_voltage_tolerance_fraction", 0.25))
    tolerance_v = max(1.0, abs(target_loop_voltage) * tolerance_fraction)

    average_cs_voltage = float(diagnostics.get("average_cs_drive_voltage_V", 0.0))
    average_plasma_voltage = float(diagnostics.get("average_plasma_circuit_voltage_V", 0.0))
    field = diagnostics.get("breakdown_field", {})
    br_t = abs(float(field.get("Br_T", 0.0)))
    bz_t = abs(float(field.get("Bz_T", 0.0)))
    zero_tolerance = float(config["constraints"]["breakdown_zero_field_tolerance_T"])

    checks = [
        _check(
            "cs_loop_voltage_tracking",
            abs(average_cs_voltage - target_loop_voltage) <= tolerance_v,
            "检查 CS 互感常数、目标 loop voltage 或 CS swing 分担比例。",
        ),
        _check(
            "plasma_circuit_voltage_reasonable",
            average_plasma_voltage <= target_loop_voltage + tolerance_v,
            "降低 Ip_seed、延长 Breakdown 时间，或调整等效 Rp/Lp 参数。",
        ),
        _check(
            "breakdown_Br_component",
            br_t <= zero_tolerance,
            "调整 PF 场影响系数或 PF3/PF4 零场预置目标。",
        ),
        _check(
            "breakdown_Bz_component",
            bz_t <= zero_tolerance,
            "调整 PF 场影响系数或 PF3/PF4 零场预置目标。",
        ),
    ]
    return checks


def _field_name(coil_name: str) -> str:
    if coil_name == "VS":
        return "I_VS_bias_MA"
    return f"I_{coil_name}_MA"


def _check(name: str, passed: bool, suggestion: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "suggestion": "" if passed else suggestion,
    }
