"""Ramp-up 阶段验证。

验证目标保持最小闭环：输入结构、时间与交接、Ip 爬升、线圈限幅、变化率、
伏秒预算、位形演化和 handoff_to_stage_3 完整性。
"""

from __future__ import annotations

from typing import Any


REQUIRED_TOP_LEVEL = (
    "metadata",
    "handoff_from_stage_1",
    "targets",
    "waveform_strategy",
    "engineering_limits",
    "physics_constraints",
    "control_constraints",
)
COILS = ("CS1", "CS2", "CS3", "PF1", "PF2", "PF3", "PF4", "Div1", "Div2")
ALL_COILS = COILS + ("VS",)


def validate_config(config: dict[str, Any]) -> None:
    """验证 Ramp-up 配置的基本结构和数值。"""

    for key in REQUIRED_TOP_LEVEL:
        if key not in config:
            raise ValueError(f"missing required top-level field: {key}")

    metadata = config["metadata"]
    if metadata.get("stage") != "rampup":
        raise ValueError("metadata.stage must be rampup")

    handoff = config["handoff_from_stage_1"]
    if not handoff.get("plasma_state", {}).get("breakdown_success", False):
        raise ValueError("handoff_from_stage_1.plasma_state.breakdown_success must be true")
    start_time = float(handoff["time_s"])
    start_ip = float(handoff["plasma_current_MA"])
    if start_ip < 0:
        raise ValueError("handoff_from_stage_1.plasma_current_MA must be non-negative")

    targets = config["targets"]
    end_time = float(targets["end_time_s"])
    target_ip = float(targets["target_plasma_current_MA"])
    if end_time <= start_time:
        raise ValueError("targets.end_time_s must be greater than handoff start time")
    if target_ip <= start_ip:
        raise ValueError("targets.target_plasma_current_MA must be greater than start plasma current")

    time_grid = config["waveform_strategy"]["time_grid"]
    step = float(time_grid["step_s"])
    if step <= 0:
        raise ValueError("waveform_strategy.time_grid.step_s must be greater than 0")
    if step > end_time - start_time:
        raise ValueError("waveform_strategy.time_grid.step_s should not exceed ramp-up duration")

    _validate_breakpoints(config, start_time, end_time, start_ip, target_ip)
    _validate_engineering_limits(config)
    _validate_physics_constraints(config)


def validate_rampup_result(config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """返回 Ramp-up 结果验证报告。"""

    rows = result["rampup_waveform"]
    checks: list[dict[str, Any]] = []
    checks.append(_check_time_axis(config, rows))
    checks.append(_check_ip_target(config, rows))
    checks.append(_check_ip_ramp_rate(config, rows))
    checks.extend(_check_current_limits(config, rows))
    checks.extend(_check_rate_limits(config, rows))
    checks.append(_check_loop_voltage(config, rows))
    checks.append(_check_physics_diagnostics_available(rows))
    checks.append(_check_cs_mutual_tracking(config, rows))
    checks.append(_check_plasma_inductance(rows))
    checks.append(_check_plasma_resistance(rows))
    checks.append(_check_flux_budget(config, rows))
    checks.append(_check_cs_flux_remaining_margin(config, rows))
    checks.append(_check_q95(config, rows))
    checks.append(_check_internal_inductance(config, rows))
    checks.append(_check_vertical_stability(config, rows))
    checks.append(_check_shape_limits(config, rows))
    checks.append(_check_pf_balance_residual(config, rows))
    checks.append(_check_handoff(result))
    checks.append(_check_handoff_physics_fields(result))
    checks.append(_check_continuity(rows))

    issues = [check for check in checks if not check["passed"]]
    warnings = [check for check in checks if check.get("level") == "warning" and not check["passed"]]
    return {
        "passed": len(issues) == 0,
        "checks": checks,
        "issues": issues,
        "warnings": warnings,
    }


def _validate_breakpoints(
    config: dict[str, Any],
    start_time: float,
    end_time: float,
    start_ip: float,
    target_ip: float,
) -> None:
    breakpoints = config["waveform_strategy"]["current_ramp"]["breakpoints"]
    if len(breakpoints) < 2:
        raise ValueError("current_ramp.breakpoints must contain at least two points")
    times = [float(point["time_s"]) for point in breakpoints]
    currents = [float(point["plasma_current_MA"]) for point in breakpoints]
    if abs(times[0] - start_time) > 1e-9:
        raise ValueError("first current_ramp breakpoint must match handoff start time")
    if abs(times[-1] - end_time) > 1e-9:
        raise ValueError("last current_ramp breakpoint must match targets.end_time_s")
    if abs(currents[0] - start_ip) > 1e-6:
        raise ValueError("first current_ramp current must match handoff plasma current")
    if abs(currents[-1] - target_ip) > 1e-6:
        raise ValueError("last current_ramp current must match target plasma current")
    if any(t2 <= t1 for t1, t2 in zip(times, times[1:])):
        raise ValueError("current_ramp breakpoint time must be strictly increasing")
    if any(i2 < i1 for i1, i2 in zip(currents, currents[1:])):
        raise ValueError("current_ramp plasma current should be monotonic increasing")


def _validate_engineering_limits(config: dict[str, Any]) -> None:
    limits = config["engineering_limits"]
    coil_limits = limits["coil_currents"]
    for name in COILS:
        if name not in coil_limits:
            raise ValueError(f"missing engineering_limits.coil_currents.{name}")
        coil = coil_limits[name]
        if float(coil["min_kA"]) > float(coil["max_kA"]):
            raise ValueError(f"{name}.min_kA must not be greater than max_kA")
        if float(coil["max_slew_rate_kA_per_s"]) <= 0:
            raise ValueError(f"{name}.max_slew_rate_kA_per_s must be greater than 0")

    flux = limits["flux"]
    if float(flux["total_available_Wb"]) <= 0:
        raise ValueError("engineering_limits.flux.total_available_Wb must be greater than 0")
    if float(flux["max_stage_2_consumption_Wb"]) <= 0:
        raise ValueError("engineering_limits.flux.max_stage_2_consumption_Wb must be greater than 0")


def _validate_physics_constraints(config: dict[str, Any]) -> None:
    physics = config["physics_constraints"]
    if float(physics["q95"]["min"]) <= 0:
        raise ValueError("physics_constraints.q95.min must be greater than 0")
    if float(physics["vertical_stability"]["min_margin"]) <= 0:
        raise ValueError("physics_constraints.vertical_stability.min_margin must be greater than 0")


def _check_time_axis(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    start = float(config["handoff_from_stage_1"]["time_s"])
    end = float(config["targets"]["end_time_s"])
    times = [float(row["time_s"]) for row in rows]
    passed = bool(times) and abs(times[0] - start) < 1e-9 and abs(times[-1] - end) < 1e-9
    passed = passed and all(t2 > t1 for t1, t2 in zip(times, times[1:]))
    return _check("time_axis", passed, "修正时间网格，保证起止时间与 Stage 1/Stage 3 交接一致。")


def _check_ip_target(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    target = float(config["targets"]["target_plasma_current_MA"])
    actual = float(rows[-1]["Ip_MA"])
    tolerance = float(config["control_constraints"]["tracking_tolerances"].get("plasma_current_MA", 0.05))
    return _check("ip_target", abs(actual - target) <= tolerance, "调整 current_ramp 末端目标或延长 ramp-up 时间。")


def _check_ip_ramp_rate(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    limit = float(config["engineering_limits"]["plasma_current"]["max_ramp_rate_MA_per_s"])
    passed = True
    for previous, current in zip(rows, rows[1:]):
        dt = float(current["time_s"]) - float(previous["time_s"])
        rate = abs(float(current["Ip_MA"]) - float(previous["Ip_MA"])) / dt
        if rate > limit + 1e-9:
            passed = False
            break
    return _check("ip_ramp_rate", passed, "降低 Ip 爬升斜率，或延长 ramp-up 时间。")


def _check_current_limits(config: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    limits = config["engineering_limits"]["coil_currents"]
    for name in COILS:
        field = _field_name(name)
        coil = limits[name]
        low = float(coil["min_kA"])
        high = float(coil["max_kA"])
        passed = all(low <= float(row[field]) <= high for row in rows)
        checks.append(_check(f"{name}_current_limit", passed, f"调整 {name} 目标工作点或放宽工程限幅。"))
    return checks


def _check_rate_limits(config: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    limits = config["engineering_limits"]["coil_currents"]
    for name in COILS:
        field = _field_name(name)
        rate_limit = float(limits[name]["max_slew_rate_kA_per_s"])
        passed = True
        for previous, current in zip(rows, rows[1:]):
            dt = float(current["time_s"]) - float(previous["time_s"])
            rate = abs(float(current[field]) - float(previous[field])) / dt
            if rate > rate_limit + 1e-9:
                passed = False
                break
        checks.append(_check(f"{name}_slew_rate", passed, f"平滑 {name} 波形或降低变化幅度。"))
    return checks


def _check_loop_voltage(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    limit = config["engineering_limits"]["loop_voltage"]
    low = float(limit["min_V"])
    high = float(limit["max_V"])
    passed = all(low <= float(row["loop_voltage_V"]) <= high for row in rows)
    return _check("loop_voltage_limit", passed, "限制 loop_voltage_profile 的上下界。")


def _check_flux_budget(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    flux = config["engineering_limits"]["flux"]
    start = float(flux["already_consumed_Wb"])
    end = float(rows[-1]["flux_consumed_Wb"])
    stage_used = end - start
    total_available = float(flux["total_available_Wb"])
    stage_limit = min(float(flux["max_stage_2_consumption_Wb"]), float(config["targets"]["max_flux_consumption_Wb"]))
    passed = end <= total_available and stage_used <= stage_limit
    return _check("cs_flux_budget", passed, "降低 ramp-up 环电压、缩短高电压持续时间或提高伏秒预算。")


def _check_physics_diagnostics_available(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required = (
        "plasma_inductance_H",
        "plasma_resistance_ohm",
        "loop_voltage_required_V",
        "loop_voltage_cs_V",
        "Bv_required_T",
        "pf_balance_residual",
    )
    passed = all(field in rows[0] for field in required)
    return _check("physics_diagnostics_available", passed, "补齐 Ramp-up 物理诊断字段。")


def _check_cs_mutual_tracking(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    tolerance = float(config["control_constraints"]["tracking_tolerances"].get("loop_voltage_V", 0.5))
    tolerance = max(tolerance, 0.01 * max(abs(float(row["loop_voltage_required_V"])) for row in rows))
    if "loop_voltage_required_V" not in rows[0] or "loop_voltage_cs_V" not in rows[0]:
        return _check("cs_mutual_tracking", False, "输出 loop_voltage_required_V 和 loop_voltage_cs_V 后再检查 CS 互感跟踪。")
    max_error = max(abs(float(row["loop_voltage_required_V"]) - float(row["loop_voltage_cs_V"])) for row in rows)
    return _check("cs_mutual_tracking", max_error <= tolerance, "调整 CS 互感、CS share，或降低环电压需求。")


def _check_plasma_inductance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if "plasma_inductance_H" not in rows[0]:
        return _check("plasma_inductance_positive", False, "输出 plasma_inductance_H。")
    passed = all(0.0 < float(row["plasma_inductance_H"]) < 1.0e-3 for row in rows)
    return _check("plasma_inductance_positive", passed, "检查 R/a/li 输入，保证等离子体电感为正且数量级合理。")


def _check_plasma_resistance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if "plasma_resistance_ohm" not in rows[0]:
        return _check("plasma_resistance_non_negative", False, "输出 plasma_resistance_ohm。")
    passed = all(0.0 <= float(row["plasma_resistance_ohm"]) < 1.0 for row in rows)
    return _check("plasma_resistance_non_negative", passed, "检查电阻模型，保证 Rp 非负且不过大。")


def _check_cs_flux_remaining_margin(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_available = float(config["engineering_limits"]["flux"]["total_available_Wb"])
    margin_fraction = float(config.get("physics_constraints", {}).get("flux_margin", {}).get("min_fraction", 0.10))
    remaining = float(rows[-1].get("cs_flux_remaining_Wb", total_available - float(rows[-1]["flux_consumed_Wb"])))
    passed = total_available > 0 and remaining / total_available >= margin_fraction
    return _check("cs_flux_remaining_margin", passed, "降低 ramp-up 伏秒消耗或提高总伏秒预算。")


def _check_q95(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    minimum = float(config["physics_constraints"]["q95"]["min"])
    passed = all(float(row["q95"]) >= minimum for row in rows)
    return _check("q95_minimum", passed, "降低目标电流斜率或调整位形参数以提高 q95 裕度。")


def _check_internal_inductance(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    limit = config["physics_constraints"]["internal_inductance"]
    low = float(limit["min"])
    high = float(limit["max"])
    passed = all(low <= float(row["internal_inductance"]) <= high for row in rows)
    return _check("internal_inductance_range", passed, "调整电流扩散假设或放慢爬升。")


def _check_vertical_stability(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    minimum = float(config["physics_constraints"]["vertical_stability"]["min_margin"])
    passed = all(float(row["vertical_stability_margin"]) >= minimum for row in rows)
    return _check("vertical_stability_margin", passed, "降低 ramp-up 末端拉长比，或提高 VS/PF 稳定裕度。")


def _check_shape_limits(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    limits = config["physics_constraints"]["plasma_shape"]
    checks = []
    for field, limit_name in (
        ("elongation", "elongation"),
        ("triangularity", "triangularity"),
        ("minor_radius_m", "minor_radius_m"),
    ):
        low = float(limits[limit_name]["min"])
        high = float(limits[limit_name]["max"])
        checks.append(all(low <= float(row[field]) <= high for row in rows))
    return _check("shape_limits", all(checks), "调整 target_shape 或放慢 shape_evolution。")


def _check_pf_balance_residual(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    tolerance = float(config.get("physics_constraints", {}).get("pf_balance", {}).get("max_residual", 0.20))
    if "pf_balance_residual" not in rows[0]:
        return _check("pf_balance_residual", False, "输出 pf_balance_residual。")
    passed = all(float(row["pf_balance_residual"]) <= tolerance for row in rows)
    return _check("pf_balance_residual", passed, "调整 PF 响应矩阵、正则化权重或降低目标位形速度。")


def _check_handoff(result: dict[str, Any]) -> dict[str, Any]:
    handoff = result.get("handoff_to_stage_3", {})
    required = ("time_s", "plasma_current_MA", "loop_voltage_V", "flux_consumed_Wb", "flux_remaining_Wb", "target_shape", "coil_currents_kA", "constraint_status")
    passed = all(key in handoff for key in required)
    return _check("handoff_to_stage_3_complete", passed, "补齐传递给 Stage 3 的末态字段。")


def _check_handoff_physics_fields(result: dict[str, Any]) -> dict[str, Any]:
    handoff = result.get("handoff_to_stage_3", {})
    required = ("cs_flux_remaining_after_rampup_Vs", "internal_inductance", "vertical_stability_margin", "physics_diagnostics")
    passed = all(key in handoff for key in required)
    return _check("handoff_physics_fields_complete", passed, "补齐 Stage 3 所需的 Ramp-up 物理交接字段。")


def _check_continuity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    monitored_fields = [
        "Ip_MA",
        "q95",
        "internal_inductance",
        "vertical_stability_margin",
        "major_radius_m",
        "minor_radius_m",
        "elongation",
        "triangularity",
        "vertical_position_m",
        "I_CS1_kA",
        "I_CS2_kA",
        "I_CS3_kA",
        "I_PF1_kA",
        "I_PF2_kA",
        "I_PF3_kA",
        "I_PF4_kA",
        "I_Div1_kA",
        "I_Div2_kA",
    ]
    numeric_fields = [field for field in monitored_fields if field in rows[0]]
    passed = True
    for previous, current in zip(rows, rows[1:]):
        dt = float(current["time_s"]) - float(previous["time_s"])
        for field in numeric_fields:
            previous_value = float(previous[field])
            current_value = float(current[field])
            scale = max(abs(previous_value), abs(current_value), 1.0)
            if abs(current_value - previous_value) > max(5000.0, 1.25 * scale) and dt > 0:
                passed = False
                break
        if not passed:
            break
    return _check("waveform_continuity", passed, "增加时间分辨率或使用更平滑的过渡函数。")


def _field_name(coil_name: str) -> str:
    return f"I_{coil_name}_kA"


def _check(name: str, passed: bool, suggestion: str, level: str = "error") -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "level": level,
        "suggestion": "" if passed else suggestion,
    }
