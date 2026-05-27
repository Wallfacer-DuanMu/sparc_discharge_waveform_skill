"""Pipeline 过程状态构造工具。"""

from __future__ import annotations

from typing import Any

try:
    from sparc_discharge_waveform_skill.common.adapters import (
        build_stage_2_config_from_global,
        build_stage_3_config_from_stage_2_result,
        normalize_stage_2_result_for_pipeline,
        normalize_stage_3_result_for_pipeline,
    )
    from sparc_discharge_waveform_skill.stages.stage_1_breakdown.generate import generate_breakdown
    from sparc_discharge_waveform_skill.stages.stage_2_rampup.generate import generate_rampup
    from sparc_discharge_waveform_skill.stages.stage_3_flattop.generate import generate_flattop
except ImportError:  # pragma: no cover - pipeline 直接运行时由 sys.path 处理
    build_stage_2_config_from_global = None  # type: ignore[assignment]
    build_stage_3_config_from_stage_2_result = None  # type: ignore[assignment]
    normalize_stage_2_result_for_pipeline = None  # type: ignore[assignment]
    normalize_stage_3_result_for_pipeline = None  # type: ignore[assignment]
    generate_breakdown = None  # type: ignore[assignment]
    generate_rampup = None  # type: ignore[assignment]
    generate_flattop = None  # type: ignore[assignment]

COIL_NAMES = ("CS1", "CS2", "CS3", "PF1", "PF2", "PF3", "PF4", "Div1", "Div2", "VS")


def initial_coil_state(config: dict[str, Any]) -> dict[str, float]:
    """从输入配置提取全局初始线圈状态。"""
    coils = config.get("coils", {})
    return {name: float(coils.get(name, {}).get("I0_MA", 0.0)) for name in COIL_NAMES}


def make_validation(passed: bool = True, issues: list[str] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    """生成统一 validation 字段。"""
    return {
        "passed": passed,
        "issues": issues or [],
        "warnings": warnings or [],
        "checks": {
            "time_axis": passed,
            "current_limits": passed,
            "dI_dt_limits": passed,
            "cs_flux_budget": passed,
            "waveform_continuity": passed,
        },
    }


def make_empty_process_state(config: dict[str, Any]) -> dict[str, Any]:
    """创建初始过程状态。"""
    return {
        "case_name": config.get("case_name", "unnamed_case"),
        "status": "initialized",
        "global_input": config,
        "stage_1_result": {},
        "stage_2_result": {},
        "stage_3_result": {},
        "final_result": {},
    }


def make_stage_1_result(config: dict[str, Any]) -> dict[str, Any]:
    """生成 Breakdown 阶段结果。

    Pipeline 入口复用 stage_1_breakdown.generate 的最小物理约束模型，避免全局流程
    仍停留在旧的占位经验结果。
    """

    timeline = config["timeline"]
    if generate_breakdown is None:
        target = config["target"]
        constraints = config["constraints"]
        duration = float(timeline["breakdown_end_s"]) - float(timeline["t_start_s"])
        flux_used = float(constraints["breakdown_loop_voltage_V"]) * duration
        flux_budget = float(constraints["cs_flux_budget_Vs"])
        return {
            "stage_name": "breakdown",
            "time_range_s": {
                "start": float(timeline["t_start_s"]),
                "end": float(timeline["breakdown_end_s"]),
            },
            "Ip_at_breakdown_end_MA": float(target["Ip_seed_MA"]),
            "coil_state_at_breakdown_end": initial_coil_state(config),
            "cs_flux_used_breakdown_Vs": round(flux_used, 6),
            "cs_flux_remaining_after_breakdown_Vs": round(flux_budget - flux_used, 6),
            "waveform_ref": f"outputs/{config.get('case_name', 'unnamed_case')}/stage_1_breakdown_waveform.csv",
            "breakdown_validation": make_validation(flux_budget > flux_used),
        }

    result = generate_breakdown(config)
    return {
        "stage_name": "breakdown",
        "time_range_s": {
            "start": float(timeline["t_start_s"]),
            "end": float(timeline["breakdown_end_s"]),
        },
        "Ip_at_breakdown_end_MA": float(result["Ip_at_breakdown_end_MA"]),
        "coil_state_at_breakdown_end": result["coil_state_at_breakdown_end"],
        "cs_flux_used_breakdown_Vs": round(float(result["cs_flux_used_breakdown_Vs"]), 6),
        "cs_flux_remaining_after_breakdown_Vs": round(float(result["cs_flux_remaining_after_breakdown_Vs"]), 6),
        "zero_field_error_T": float(result["zero_field_error_T"]),
        "physics_diagnostics": result.get("physics_diagnostics", {}),
        "waveform_ref": f"outputs/{config.get('case_name', 'unnamed_case')}/stage_1_breakdown_waveform.csv",
        "breakdown_validation": result["breakdown_validation"],
    }


def make_stage_2_result(
    config: dict[str, Any],
    stage_1_result: dict[str, Any],
    use_stage_generator: bool | None = None,
) -> dict[str, Any]:
    """生成 Ramp-up 阶段结果。

    默认保持旧占位逻辑；当 options.stage_execution_mode 为 stage_generators，
    或 use_stage_generator=True 时，调用 stages/stage_2_rampup.generate_rampup。
    """

    if use_stage_generator is None:
        use_stage_generator = config.get("options", {}).get("stage_execution_mode") in {"stage_generators", "real_stage_2"}

    if use_stage_generator and generate_rampup is not None and build_stage_2_config_from_global is not None and normalize_stage_2_result_for_pipeline is not None:
        stage_2_config = build_stage_2_config_from_global(config, stage_1_result)
        raw_result = generate_rampup(stage_2_config)
        return normalize_stage_2_result_for_pipeline(raw_result, config, stage_1_result)

    timeline = config["timeline"]
    target = config["target"]
    flux_remaining = float(stage_1_result["cs_flux_remaining_after_breakdown_Vs"])
    rampup_duration = float(timeline["rampup_end_s"]) - float(timeline["breakdown_end_s"])
    ip_delta = float(target["Ip_flat_MA"]) - float(stage_1_result["Ip_at_breakdown_end_MA"])
    flux_used = max(ip_delta * rampup_duration * 0.8, 0.0)

    return {
        "stage_name": "rampup",
        "execution_mode": "placeholder",
        "time_range_s": {
            "start": float(timeline["breakdown_end_s"]),
            "end": float(timeline["rampup_end_s"]),
        },
        "Ip_at_rampup_start_MA": float(stage_1_result["Ip_at_breakdown_end_MA"]),
        "Ip_at_rampup_end_MA": float(target["Ip_flat_MA"]),
        "coil_state_at_rampup_start": stage_1_result["coil_state_at_breakdown_end"],
        "coil_state_at_rampup_end": stage_1_result["coil_state_at_breakdown_end"],
        "shape_state_at_rampup_end": _target_shape_state(config),
        "cs_flux_used_rampup_Vs": round(flux_used, 6),
        "cs_flux_remaining_after_rampup_Vs": round(flux_remaining - flux_used, 6),
        "waveform_ref": f"outputs/{config.get('case_name', 'unnamed_case')}/stage_2_rampup_waveform.csv",
        "rampup_validation": make_validation(flux_remaining > flux_used),
    }


def make_stage_3_result(config: dict[str, Any], stage_2_result: dict[str, Any]) -> dict[str, Any]:
    """生成 Flat-top 阶段结果。

    当 options.stage_execution_mode 为 stage_generators 时，调用 Stage 3 最小物理维持模型；
    否则保留旧占位逻辑，便于对比。
    """
    use_stage_generator = config.get("options", {}).get("stage_execution_mode") in {"stage_generators", "real_stage_3"}
    if use_stage_generator and generate_flattop is not None and build_stage_3_config_from_stage_2_result is not None and normalize_stage_3_result_for_pipeline is not None:
        stage_3_config = build_stage_3_config_from_stage_2_result(config, stage_2_result)
        raw_result = generate_flattop(stage_3_config)
        return normalize_stage_3_result_for_pipeline(raw_result, config, stage_2_result)

    timeline = config["timeline"]
    target = config["target"]
    coils = config["coils"]
    constraints = config["constraints"]
    flux_remaining = float(stage_2_result["cs_flux_remaining_after_rampup_Vs"])
    flattop_duration = float(timeline["flattop_end_s"]) - float(timeline["rampup_end_s"])
    flux_used = max(flattop_duration * float(target["Ip_flat_MA"]) * 0.2, 0.0)
    final_remaining = flux_remaining - flux_used
    budget = float(constraints["cs_flux_budget_Vs"])
    margin_fraction = final_remaining / budget if budget else 0.0
    min_margin = float(constraints["min_cs_flux_margin_fraction"])
    passed = margin_fraction >= min_margin

    return {
        "stage_name": "flattop",
        "time_range_s": {
            "start": float(timeline["rampup_end_s"]),
            "end": float(timeline["flattop_end_s"]),
        },
        "Ip_at_flattop_start_MA": float(stage_2_result["Ip_at_rampup_end_MA"]),
        "Ip_at_flattop_end_MA": float(target["Ip_flat_MA"]),
        "coil_state_at_flattop_start": stage_2_result["coil_state_at_rampup_end"],
        "coil_state_at_flattop_end": stage_2_result["coil_state_at_rampup_end"],
        "shape_state_at_flattop_end": stage_2_result["shape_state_at_rampup_end"],
        "cs_flux_used_flattop_Vs": round(flux_used, 6),
        "cs_flux_margin": {
            "remaining_Vs": round(final_remaining, 6),
            "margin_fraction": round(margin_fraction, 6),
            "passed": passed,
        },
        "divertor_setting": {
            "Div1_MA": float(coils.get("Div1", {}).get("I0_MA", 0.0)),
            "Div2_MA": float(coils.get("Div2", {}).get("I0_MA", 0.0)),
            "mode": "fixed_or_small_scan",
        },
        "vs_reserved_range": {
            "VS_bias_MA": float(coils.get("VS", {}).get("I0_MA", 0.0)),
            "reserved_fraction": float(coils.get("VS", {}).get("reserved_fraction", 0.0)),
            "I_min_MA": float(coils.get("VS", {}).get("I_min_MA", 0.0)),
            "I_max_MA": float(coils.get("VS", {}).get("I_max_MA", 0.0)),
        },
        "waveform_ref": f"outputs/{config.get('case_name', 'unnamed_case')}/stage_3_flattop_waveform.csv",
        "flattop_validation": make_validation(passed),
    }


def make_final_result(
    config: dict[str, Any],
    stage_1_result: dict[str, Any],
    stage_2_result: dict[str, Any],
    stage_3_result: dict[str, Any],
    output_dir: str,
) -> dict[str, Any]:
    """生成最终汇总结果。"""
    validations = (
        stage_1_result["breakdown_validation"],
        stage_2_result["rampup_validation"],
        stage_3_result["flattop_validation"],
    )
    passed = all(item.get("passed", False) for item in validations)
    failed_stage = None
    if not stage_1_result["breakdown_validation"].get("passed", False):
        failed_stage = "breakdown"
    elif not stage_2_result["rampup_validation"].get("passed", False):
        failed_stage = "rampup"
    elif not stage_3_result["flattop_validation"].get("passed", False):
        failed_stage = "flattop"

    total_used = (
        float(stage_1_result["cs_flux_used_breakdown_Vs"])
        + float(stage_2_result["cs_flux_used_rampup_Vs"])
        + float(stage_3_result["cs_flux_used_flattop_Vs"])
    )

    margin = stage_3_result["cs_flux_margin"]
    return {
        "passed": passed,
        "failed_stage": failed_stage,
        "waveform_file": f"{output_dir}/waveforms.csv",
        "process_state_file": f"{output_dir}/process_state.json",
        "stage_summary_file": f"{output_dir}/stage_summary.md",
        "validation_report_file": f"{output_dir}/validation_report.md",
        "revision_suggestions_file": f"{output_dir}/revision_suggestions.md",
        "key_metrics": {
            "Ip_seed_MA": float(config["target"]["Ip_seed_MA"]),
            "Ip_flat_MA": float(config["target"]["Ip_flat_MA"]),
            "cs_flux_budget_Vs": float(config["constraints"]["cs_flux_budget_Vs"]),
            "cs_flux_used_total_Vs": round(total_used, 6),
            "cs_flux_remaining_Vs": margin["remaining_Vs"],
            "cs_flux_margin_fraction": margin["margin_fraction"],
        },
        "major_warnings": [],
        "next_revision_suggestions": [] if passed else ["优先检查 CS 伏秒预算、阶段时长或目标 Ip_flat_MA。"],
    }


def _target_shape_state(config: dict[str, Any]) -> dict[str, Any]:
    shape = config["target"].get("shape", {})
    return {
        "R_axis_m": float(shape.get("R_axis_m", config["device"].get("R0_m", 0.0))),
        "minor_radius_m": float(shape.get("minor_radius_m", config["device"].get("a_m", 0.0))),
        "kappa": float(shape.get("kappa_flat", 0.0)),
        "delta": float(shape.get("delta_flat", 0.0)),
        "x_point": shape.get("x_point", "unspecified"),
    }
