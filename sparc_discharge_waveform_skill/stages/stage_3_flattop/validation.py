"""Flat-top 阶段验证。

验证目标保持最小闭环：输入结构、Stage 2 交接、平台电流保持、线圈限幅、
变化率、伏秒裕度、位形/X 点/打击点保持和 final_state 完整性。
"""

from __future__ import annotations

from typing import Any


REQUIRED_TOP_LEVEL = (
    "metadata",
    "handoff_from_stage_2",
    "targets",
    "waveform_strategy",
    "engineering_limits",
    "physics_constraints",
    "control_constraints",
    "outputs",
    "validation",
)
COILS = ("CS1", "CS2", "CS3", "PF1", "PF2", "PF3", "PF4", "Div1", "Div2", "VS")


def validate_config(config: dict[str, Any]) -> None:
    """验证 Flat-top 配置的基本结构和数值。"""

    for key in REQUIRED_TOP_LEVEL:
        if key not in config:
            raise ValueError(f"missing required top-level field: {key}")

    metadata = config["metadata"]
    if metadata.get("stage") != "flattop":
        raise ValueError("metadata.stage must be flattop")

    handoff = config["handoff_from_stage_2"]
    if handoff.get("source_stage") != "rampup":
        raise ValueError("handoff_from_stage_2.source_stage must be rampup")
    if str(handoff.get("constraint_status", {}).get("stage_2_status", "")).lower() not in {"valid", "passed", "warning"}:
        raise ValueError("handoff_from_stage_2.constraint_status.stage_2_status must indicate a usable Stage 2 result")

    start_time = float(handoff["time_s"])
    start_ip = float(handoff["plasma_current_MA"])
    if start_ip <= 0:
        raise ValueError("handoff_from_stage_2.plasma_current_MA must be greater than 0")
    if float(handoff["flux_remaining_Wb"]) <= 0:
        raise ValueError("handoff_from_stage_2.flux_remaining_Wb must be greater than 0")
    _validate_handoff_fields(handoff)

    targets = config["targets"]
    end_time = float(targets["end_time_s"])
    target_ip = float(targets["target_plasma_current_MA"])
    if end_time <= start_time:
        raise ValueError("targets.end_time_s must be greater than handoff start time")
    if target_ip <= 0:
        raise ValueError("targets.target_plasma_current_MA must be greater than 0")
    if float(targets["allowed_current_deviation_MA"]) < 0:
        raise ValueError("targets.allowed_current_deviation_MA must be non-negative")

    time_grid = config["waveform_strategy"]["time_grid"]
    if abs(float(time_grid["start_time_s"]) - start_time) > 1e-9:
        raise ValueError("waveform_strategy.time_grid.start_time_s must match handoff_from_stage_2.time_s")
    if abs(float(time_grid["end_time_s"]) - end_time) > 1e-9:
        raise ValueError("waveform_strategy.time_grid.end_time_s must match targets.end_time_s")
    step = float(time_grid["step_s"])
    if step <= 0:
        raise ValueError("waveform_strategy.time_grid.step_s must be greater than 0")
    if step > end_time - start_time:
        raise ValueError("waveform_strategy.time_grid.step_s should not exceed flat-top duration")

    _validate_engineering_limits(config)
    _validate_physics_constraints(config)


def validate_flattop_result(config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """返回 Flat-top 结果验证报告。"""

    rows = result["flattop_waveform"]
    checks: list[dict[str, Any]] = []
    checks.append(_check_time_axis(config, rows))
    checks.append(_check_ip_hold(config, rows))
    checks.append(_check_loop_voltage(config, rows))
    checks.append(_check_flux_budget(config, rows))
    checks.extend(_check_current_limits(config, rows))
    checks.extend(_check_rate_limits(config, rows))
    checks.append(_check_q95(config, rows))
    checks.append(_check_internal_inductance(config, rows))
    checks.append(_check_vertical_stability(config, rows))
    checks.append(_check_shape_hold(config, rows))
    checks.append(_check_x_point(config, rows))
    checks.append(_check_strike_points(config, rows))
    checks.append(_check_vs_reserve(config, result))
    checks.append(_check_final_state(result))
    checks.append(_check_continuity(rows))

    issues = [check for check in checks if not check["passed"]]
    warnings = [check for check in checks if check.get("level") == "warning" and not check["passed"]]
    return {
        "passed": len(issues) == 0,
        "checks": checks,
        "issues": issues,
        "warnings": warnings,
    }


def _validate_handoff_fields(handoff: dict[str, Any]) -> None:
    """检查 Stage 2 交接给 Flat-top 的最小状态。"""

    if "target_shape" not in handoff:
        raise ValueError("handoff_from_stage_2.target_shape is required")
    if "coil_currents_kA" not in handoff:
        raise ValueError("handoff_from_stage_2.coil_currents_kA is required")
    if "q95" not in handoff:
        raise ValueError("handoff_from_stage_2.q95 is required")

    shape = handoff["target_shape"]
    for field in ("major_radius_m", "minor_radius_m", "elongation", "triangularity", "vertical_position_m"):
        if field not in shape:
            raise ValueError(f"handoff_from_stage_2.target_shape.{field} is required")

    currents = handoff["coil_currents_kA"]
    for name in COILS:
        if name not in currents:
            raise ValueError(f"handoff_from_stage_2.coil_currents_kA.{name} is required")


def _validate_engineering_limits(config: dict[str, Any]) -> None:
    limits = config["engineering_limits"]
    for name in COILS:
        coil = limits["coil_currents"].get(name)
        if coil is None:
            raise ValueError(f"missing engineering_limits.coil_currents.{name}")
        if float(coil["min_kA"]) > float(coil["max_kA"]):
            raise ValueError(f"{name}.min_kA must not be greater than max_kA")
        if float(coil["max_slew_rate_kA_per_s"]) <= 0:
            raise ValueError(f"{name}.max_slew_rate_kA_per_s must be greater than 0")

    flux = limits["flux"]
    if float(flux["total_available_Wb"]) <= 0:
        raise ValueError("engineering_limits.flux.total_available_Wb must be greater than 0")
    if float(flux["max_stage_3_consumption_Wb"]) <= 0:
        raise ValueError("engineering_limits.flux.max_stage_3_consumption_Wb must be greater than 0")


def _validate_physics_constraints(config: dict[str, Any]) -> None:
    physics = config["physics_constraints"]
    if float(physics["q95"]["min"]) <= 0:
        raise ValueError("physics_constraints.q95.min must be greater than 0")
    if float(physics["vertical_stability"]["min_margin"]) <= 0:
        raise ValueError("physics_constraints.vertical_stability.min_margin must be greater than 0")


def _check_time_axis(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    start = float(config["handoff_from_stage_2"]["time_s"])
    end = float(config["targets"]["end_time_s"])
    times = [float(row["time_s"]) for row in rows]
    passed = bool(times) and abs(times[0] - start) < 1e-9 and abs(times[-1] - end) < 1e-9
    passed = passed and all(t2 > t1 for t1, t2 in zip(times, times[1:]))
    return _check("time_axis", passed, "修正时间网格，保证与 Stage 2 交接和最终平顶结束时间一致。")


def _check_ip_hold(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    target = float(config["targets"]["target_plasma_current_MA"])
    tolerance = float(config["targets"]["allowed_current_deviation_MA"])
    control_tolerance = float(config["control_constraints"]["tracking_tolerances"].get("plasma_current_MA", tolerance))
    effective_tolerance = min(tolerance, control_tolerance)
    passed = all(abs(float(row["Ip_MA"]) - target) <= effective_tolerance + 1e-9 for row in rows)
    return _check("ip_hold", passed, "减小平台电流波动，或放宽允许偏差。")


def _check_loop_voltage(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    limit = config["engineering_limits"]["loop_voltage"]
    low = float(limit["min_V"])
    high = float(limit["max_V"])
    target = float(config["targets"]["target_loop_voltage_V"])
    tolerance = float(config["control_constraints"]["tracking_tolerances"].get("loop_voltage_V", 0.3))
    within_limit = all(low <= float(row["loop_voltage_V"]) <= high for row in rows)
    near_target = all(abs(float(row["loop_voltage_V"]) - target) <= tolerance + 1e-9 for row in rows[-min(len(rows), 10):])
    return _check("loop_voltage_hold", within_limit and near_target, "降低平顶后段环电压偏差或收紧低电压保持曲线。")


def _check_flux_budget(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    flux = config["engineering_limits"]["flux"]
    start = float(flux["already_consumed_Wb"])
    end = float(rows[-1]["flux_consumed_Wb"])
    stage_used = end - start
    total_available = float(flux["total_available_Wb"])
    stage_limit = min(float(flux["max_stage_3_consumption_Wb"]), float(config["targets"]["max_flux_consumption_Wb"]))
    remaining_fraction = (total_available - end) / total_available
    minimum_fraction = float(config["targets"]["min_flux_margin_fraction"])
    passed = end <= total_available and stage_used <= stage_limit and remaining_fraction >= minimum_fraction
    return _check("cs_flux_margin", passed, "降低平顶持续时间或维持电压，保留更多 CS 剩余伏秒。")


def _check_current_limits(config: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    limits = config["engineering_limits"]["coil_currents"]
    for name in COILS:
        field = _field_name(name)
        coil = limits[name]
        low = float(coil["min_kA"])
        high = float(coil["max_kA"])
        passed = all(low <= float(row[field]) <= high for row in rows)
        checks.append(_check(f"{name}_current_limit", passed, f"调整 {name} 平顶工作点或工程限幅。"))
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
        checks.append(_check(f"{name}_slew_rate", passed, f"平滑 {name} 平顶波形，降低微调幅度。"))
    return checks


def _check_q95(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    minimum = float(config["physics_constraints"]["q95"]["min"])
    passed = all(float(row["q95"]) >= minimum for row in rows)
    return _check("q95_minimum", passed, "调整平台位形或降低目标运行强度以提高 q95 裕度。")


def _check_internal_inductance(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    limit = config["physics_constraints"]["internal_inductance"]
    low = float(limit["min"])
    high = float(limit["max"])
    passed = all(low <= float(row["internal_inductance"]) <= high for row in rows)
    return _check("internal_inductance_range", passed, "调整平顶保持模型，限制电流剖面漂移。")


def _check_vertical_stability(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    minimum = float(config["physics_constraints"]["vertical_stability"]["min_margin"])
    passed = all(float(row["vertical_stability_margin"]) >= minimum for row in rows)
    return _check("vertical_stability_margin", passed, "降低拉长比或提高 VS/PF 稳定裕度。")


def _check_shape_hold(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    limits = config["physics_constraints"]["plasma_shape"]
    target_major = float(limits["major_radius_m"]["target"])
    tol_major = float(limits["major_radius_m"]["tolerance"])
    target_vertical = float(limits["vertical_position_m"]["target"])
    tol_vertical = float(limits["vertical_position_m"]["tolerance"])
    elongation = limits["elongation"]
    triangularity = limits["triangularity"]
    minor_radius = limits["minor_radius_m"]

    passed = all(abs(float(row["major_radius_m"]) - target_major) <= tol_major + 1e-9 for row in rows)
    passed = passed and all(abs(float(row["vertical_position_m"]) - target_vertical) <= tol_vertical + 1e-9 for row in rows)
    passed = passed and all(float(elongation["min"]) <= float(row["elongation"]) <= float(elongation["max"]) for row in rows)
    passed = passed and all(float(triangularity["min"]) <= float(row["triangularity"]) <= float(triangularity["max"]) for row in rows)
    passed = passed and all(float(minor_radius["min"]) <= float(row["minor_radius_m"]) <= float(minor_radius["max"]) for row in rows)
    return _check("shape_hold", passed, "调整 PF 工作点和位形保持策略，收紧平顶形状漂移。")


def _check_x_point(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    target_shape = config["targets"]["target_shape"]
    x_point = target_shape.get("x_point", {})
    lower = x_point.get("lower_x_point", {})
    tolerance = float(x_point.get("tolerance_m", config["control_constraints"]["tracking_tolerances"].get("x_point_position_m", 0.03)))
    r_target = float(lower.get("R_m", 1.55))
    z_target = float(lower.get("Z_m", -1.05))
    passed = all(abs(float(row["lower_x_point_R_m"]) - r_target) <= tolerance + 1e-9 for row in rows)
    passed = passed and all(abs(float(row["lower_x_point_Z_m"]) - z_target) <= tolerance + 1e-9 for row in rows)
    return _check("x_point_hold", passed, "调整 PF3/PF4 保持策略，减小 X 点漂移。")


def _check_strike_points(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    divertor = config["targets"]["divertor_targets"]
    tolerance = float(config["control_constraints"]["tracking_tolerances"].get("strike_point_position_m", 0.04))
    outer = divertor["strike_point_lower_outer"]
    inner = divertor["strike_point_lower_inner"]

    passed = all(abs(float(row["strike_point_lower_outer_R_m"]) - float(outer["R_m"])) <= tolerance + 1e-9 for row in rows)
    passed = passed and all(abs(float(row["strike_point_lower_outer_Z_m"]) - float(outer["Z_m"])) <= tolerance + 1e-9 for row in rows)
    passed = passed and all(abs(float(row["strike_point_lower_inner_R_m"]) - float(inner["R_m"])) <= tolerance + 1e-9 for row in rows)
    passed = passed and all(abs(float(row["strike_point_lower_inner_Z_m"]) - float(inner["Z_m"])) <= tolerance + 1e-9 for row in rows)
    return _check("strike_point_hold", passed, "减小 Div 扫描幅值或修正偏滤器目标。")


def _check_vs_reserve(config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    reserve = result.get("auxiliary_settings", {}).get("vs_reserved_range_kA", {})
    limits = config["engineering_limits"]["coil_currents"]["VS"]
    minimum_fraction = float(config["waveform_strategy"]["vs_reserve"].get("reserve_fraction_of_limit", 0.70))
    baseline = float(reserve.get("baseline_kA", 0.0))
    reserved_min = float(reserve.get("reserved_min_kA", baseline))
    reserved_max = float(reserve.get("reserved_max_kA", baseline))
    expected_span = minimum_fraction * (float(limits["max_kA"]) - float(limits["min_kA"]))
    actual_span = reserved_max - reserved_min
    passed = reserved_min >= float(limits["min_kA"]) and reserved_max <= float(limits["max_kA"]) and actual_span >= expected_span - 1e-9
    return _check("vs_reserve", passed, "扩大 VS 预留范围或降低平顶稳定性压力。")


def _check_final_state(result: dict[str, Any]) -> dict[str, Any]:
    final_state = result.get("final_state", {})
    required = (
        "time_s",
        "plasma_current_MA",
        "loop_voltage_V",
        "flux_consumed_Wb",
        "flux_remaining_Wb",
        "flux_margin_fraction",
        "q95",
        "shape",
        "divertor_setting",
        "vs_reserved_range_kA",
        "coil_currents_kA",
        "constraint_status",
    )
    passed = all(key in final_state for key in required)
    return _check("final_state_complete", passed, "补齐最终末态输出字段。")


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
    return _check("waveform_continuity", passed, "增加时间分辨率或减小平顶微调幅值。")


def _field_name(coil_name: str) -> str:
    if coil_name == "VS":
        return "I_VS_bias_kA"
    return f"I_{coil_name}_kA"


def _check(name: str, passed: bool, suggestion: str, level: str = "error") -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "level": level,
        "suggestion": "" if passed else suggestion,
    }
