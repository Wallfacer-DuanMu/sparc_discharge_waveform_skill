"""Pipeline 最小闭环所需的通用输入检查。"""

from __future__ import annotations

from typing import Any

REQUIRED_TOP_LEVEL_KEYS = (
    "case_name",
    "device",
    "timeline",
    "target",
    "coils",
    "constraints",
    "options",
)

DYNAMIC_COILS = ("CS1", "CS2", "CS3", "PF1", "PF2", "PF3", "PF4", "Div1", "Div2")
ALL_COILS = (*DYNAMIC_COILS, "VS")


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """检查统一输入配置，返回标准 validation 字典。"""
    issues: list[str] = []
    warnings: list[str] = []
    checks: dict[str, bool] = {}

    checks["top_level_keys"] = _check_top_level_keys(config, issues)
    checks["timeline"] = _check_timeline(config, issues)
    checks["target"] = _check_target(config, issues)
    checks["coils"] = _check_coils(config, issues, warnings)
    checks["constraints"] = _check_constraints(config, issues)
    checks["physics"] = _check_physics(config, warnings)

    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
    }


def _check_top_level_keys(config: dict[str, Any], issues: list[str]) -> bool:
    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in config]
    if missing:
        issues.append(f"缺少顶层字段: {', '.join(missing)}")
        return False
    return True


def _check_timeline(config: dict[str, Any], issues: list[str]) -> bool:
    timeline = config.get("timeline", {})
    try:
        t_start = float(timeline["t_start_s"])
        breakdown_end = float(timeline["breakdown_end_s"])
        rampup_end = float(timeline["rampup_end_s"])
        flattop_end = float(timeline["flattop_end_s"])
        dt = float(timeline["dt_s"])
    except (KeyError, TypeError, ValueError):
        issues.append("timeline 字段不完整或不是数值。")
        return False

    if not (t_start < breakdown_end < rampup_end < flattop_end):
        issues.append("时间顺序必须满足 t_start_s < breakdown_end_s < rampup_end_s < flattop_end_s。")
        return False
    if dt <= 0:
        issues.append("timeline.dt_s 必须大于 0。")
        return False
    return True


def _check_target(config: dict[str, Any], issues: list[str]) -> bool:
    target = config.get("target", {})
    try:
        ip_seed = float(target["Ip_seed_MA"])
        ip_flat = float(target["Ip_flat_MA"])
    except (KeyError, TypeError, ValueError):
        issues.append("target.Ip_seed_MA 或 target.Ip_flat_MA 缺失/非法。")
        return False

    if ip_seed < 0:
        issues.append("target.Ip_seed_MA 必须大于等于 0。")
        return False
    if ip_flat <= ip_seed:
        issues.append("target.Ip_flat_MA 必须大于 target.Ip_seed_MA。")
        return False
    if "shape" not in target:
        issues.append("target.shape 缺失。")
        return False
    return True


def _check_coils(config: dict[str, Any], issues: list[str], warnings: list[str]) -> bool:
    coils = config.get("coils", {})
    ok = True

    for coil_name in ALL_COILS:
        coil = coils.get(coil_name)
        if not isinstance(coil, dict):
            issues.append(f"coils.{coil_name} 缺失或不是对象。")
            ok = False
            continue

        try:
            i0 = float(coil["I0_MA"])
            i_min = float(coil["I_min_MA"])
            i_max = float(coil["I_max_MA"])
        except (KeyError, TypeError, ValueError):
            issues.append(f"coils.{coil_name} 的 I0_MA/I_min_MA/I_max_MA 缺失或非法。")
            ok = False
            continue

        if i_min > i_max:
            issues.append(f"coils.{coil_name} 的 I_min_MA 不能大于 I_max_MA。")
            ok = False
        if not (i_min <= i0 <= i_max):
            issues.append(f"coils.{coil_name}.I0_MA 不在限幅范围内。")
            ok = False

        if coil_name in DYNAMIC_COILS:
            try:
                d_i_dt = float(coil["dI_dt_max_MA_per_s"])
            except (KeyError, TypeError, ValueError):
                issues.append(f"coils.{coil_name}.dI_dt_max_MA_per_s 缺失或非法。")
                ok = False
            else:
                if d_i_dt <= 0:
                    issues.append(f"coils.{coil_name}.dI_dt_max_MA_per_s 必须大于 0。")
                    ok = False
        elif "reserved_fraction" not in coil:
            warnings.append("coils.VS.reserved_fraction 缺失，后续将无法明确 VS 裕度。")

    return ok


def _check_constraints(config: dict[str, Any], issues: list[str]) -> bool:
    constraints = config.get("constraints", {})
    positive_fields = ("cs_flux_budget_Vs", "breakdown_loop_voltage_V", "min_cs_flux_margin_fraction")
    ok = True

    for field in positive_fields:
        try:
            value = float(constraints[field])
        except (KeyError, TypeError, ValueError):
            issues.append(f"constraints.{field} 缺失或非法。")
            ok = False
            continue
        if value <= 0:
            issues.append(f"constraints.{field} 必须大于 0。")
            ok = False

    return ok


def _check_physics(config: dict[str, Any], warnings: list[str]) -> bool:
    physics = config.get("physics", {})
    if not physics:
        warnings.append("physics 缺失，将使用第一阶段内置最小物理约束默认值。")
        return True

    for name, value in physics.get("cs_mutual_inductance_H", {}).items():
        try:
            if float(value) <= 0:
                warnings.append(f"physics.cs_mutual_inductance_H.{name} 应大于 0。")
        except (TypeError, ValueError):
            warnings.append(f"physics.cs_mutual_inductance_H.{name} 不是有效数值。")

    if "plasma_resistance_ohm" in physics:
        try:
            if float(physics["plasma_resistance_ohm"]) < 0:
                warnings.append("physics.plasma_resistance_ohm 应大于等于 0。")
        except (TypeError, ValueError):
            warnings.append("physics.plasma_resistance_ohm 不是有效数值。")

    return True
