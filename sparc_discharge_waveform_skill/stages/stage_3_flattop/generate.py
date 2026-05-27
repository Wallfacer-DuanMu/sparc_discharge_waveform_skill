"""Flat-top 阶段主入口。

职责：读取输入配置，调用 models.py 生成候选波形，再调用 validation.py 完成检查。
本文件只做流程编排，避免把模型、验证和输出逻辑混在一起。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError("Please install PyYAML before running stage_3_flattop.generate") from exc

try:
    from .models import (
        ALL_COILS,
        build_vs_reserved_range,
        build_waveform_rows,
        compute_plasma_inductance_profile,
        compute_poloidal_beta_profile,
        compute_required_vertical_field,
        estimate_flux_consumption,
        estimate_flux_margin_fraction,
        estimate_q95_profile_from_geometry,
        estimate_vertical_stability_margin,
        extract_divertor_state,
        extract_end_state,
        extract_shape_state,
        generate_cs_waveforms_from_mutual_inductance,
        generate_div_waveforms_from_response_matrix,
        generate_internal_inductance_profile,
        generate_ip_hold_profile,
        generate_plasma_resistance_profile,
        generate_pf_waveforms_from_response_matrix,
        generate_shape_hold_profile,
        generate_strike_point_profile,
        generate_temperature_profile,
        generate_vs_bias,
        generate_x_point_profile,
        make_time_axis,
        split_loop_voltage_terms,
    )
    from .validation import validate_config, validate_flattop_result
except ImportError:  # 允许直接 python generate.py 运行
    from models import (  # type: ignore
        ALL_COILS,
        build_vs_reserved_range,
        build_waveform_rows,
        compute_plasma_inductance_profile,
        compute_poloidal_beta_profile,
        compute_required_vertical_field,
        estimate_flux_consumption,
        estimate_flux_margin_fraction,
        estimate_q95_profile_from_geometry,
        estimate_vertical_stability_margin,
        extract_divertor_state,
        extract_end_state,
        extract_shape_state,
        generate_cs_waveforms_from_mutual_inductance,
        generate_div_waveforms_from_response_matrix,
        generate_internal_inductance_profile,
        generate_ip_hold_profile,
        generate_plasma_resistance_profile,
        generate_pf_waveforms_from_response_matrix,
        generate_shape_hold_profile,
        generate_strike_point_profile,
        generate_temperature_profile,
        generate_vs_bias,
        generate_x_point_profile,
        make_time_axis,
        split_loop_voltage_terms,
    )
    from validation import validate_config, validate_flattop_result  # type: ignore


DEFAULT_CONFIG_PATH = Path(__file__).with_name("example.yaml")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "outputs" / "stage_3_flattop"


def load_config(path: str | Path) -> dict[str, Any]:
    """读取 YAML 配置。"""

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("config file must contain a YAML mapping")
    return config


def generate_flattop(config: dict[str, Any]) -> dict[str, Any]:
    """生成 Flat-top 阶段候选结果。"""

    validate_config(config)

    handoff = config["handoff_from_stage_2"]
    targets = config["targets"]
    strategy = config["waveform_strategy"]
    limits = config["engineering_limits"]
    physics = config.get("physics", {})

    t_start = float(handoff["time_s"])
    t_end = float(targets["end_time_s"])
    dt = float(strategy["time_grid"]["step_s"])
    times = make_time_axis(t_start, t_end, dt)

    ip_profile = generate_ip_hold_profile(
        times=times,
        start_ip_ma=float(handoff["plasma_current_MA"]),
        target_ip_ma=float(targets["target_plasma_current_MA"]),
        max_deviation_ma=float(targets["allowed_current_deviation_MA"]),
        smoothing_time_s=float(strategy["plasma_current_hold"].get("smoothing_time_s", 0.20)),
    )

    start_shape = _initial_shape_from_handoff(handoff)
    shape_tolerance = float(config["control_constraints"]["tracking_tolerances"].get("shape_dimension_m", 0.01))
    shape_profile = generate_shape_hold_profile(times, start_shape, targets["target_shape"], shape_tolerance)
    x_point_profile = generate_x_point_profile(
        times,
        targets["target_shape"],
        float(targets["target_shape"].get("x_point", {}).get("tolerance_m", 0.03)),
    )
    strike_point_profile = generate_strike_point_profile(times, targets["divertor_targets"])

    te_profile = generate_temperature_profile(times, physics)
    rp_profile = generate_plasma_resistance_profile(times, physics, te_profile)
    internal_inductance = generate_internal_inductance_profile(times, physics)
    lp_profile = compute_plasma_inductance_profile(shape_profile, internal_inductance)
    loop_terms = split_loop_voltage_terms(times, ip_profile, lp_profile, rp_profile)
    loop_voltage = loop_terms["required"]
    flux_consumed = estimate_flux_consumption(times, loop_voltage, float(limits["flux"]["already_consumed_Wb"]))
    stage_3_flux_used = [value - float(limits["flux"]["already_consumed_Wb"]) for value in flux_consumed]
    flux_margin_fraction = estimate_flux_margin_fraction(flux_consumed, float(limits["flux"]["total_available_Wb"]))

    beta_p_profile = compute_poloidal_beta_profile(times, physics)
    bv_required = compute_required_vertical_field(ip_profile, shape_profile, internal_inductance, beta_p_profile)
    q95_profile = estimate_q95_profile_from_geometry(
        ip_profile,
        shape_profile,
        float(physics.get("device", {}).get("B0_T", config.get("device", {}).get("B0_T", 12.2))),
        float(targets["target_q95"]),
    )
    vertical_margin = estimate_vertical_stability_margin(shape_profile, x_point_profile, targets["target_shape"])

    initial_currents = _initial_currents_from_handoff(handoff)
    cs_result = generate_cs_waveforms_from_mutual_inductance(
        times,
        initial_currents,
        loop_voltage,
        physics.get("cs_mutual_inductance_H"),
        physics.get("cs_swing_share", strategy["cs_maintenance"].get("distribute_to_coils")),
    )
    cs_waveforms = cs_result["waveforms"]
    pf_result = generate_pf_waveforms_from_response_matrix(
        times,
        initial_currents,
        targets["target_shape"],
        shape_profile,
        bv_required,
        physics,
    )
    pf_waveforms = pf_result["waveforms"]
    div_result = generate_div_waveforms_from_response_matrix(
        times,
        initial_currents,
        strike_point_profile,
        targets["divertor_targets"],
        strategy["divertor_control"],
        physics,
    )
    div_waveforms = div_result["waveforms"]
    x_point_residual = _x_point_residuals(x_point_profile, targets["target_shape"])
    vs_baseline = float(strategy["vs_reserve"].get("baseline_current_kA", initial_currents.get("VS", 0.0)))
    vs_bias = generate_vs_bias(times, vs_baseline)
    vs_reserved_range = build_vs_reserved_range(
        limits["coil_currents"]["VS"],
        float(strategy["vs_reserve"].get("reserve_fraction_of_limit", 0.70)),
        vs_baseline,
    )

    total_available_flux = float(limits["flux"]["total_available_Wb"])
    diagnostics = {
        "loop_voltage_required_V": loop_voltage,
        "loop_voltage_cs_V": cs_result["loop_voltage_cs_V"],
        "loop_voltage_inductive_V": loop_terms["inductive"],
        "loop_voltage_resistive_V": loop_terms["resistive"],
        "plasma_inductance_H": lp_profile,
        "plasma_resistance_ohm": rp_profile,
        "electron_temperature_eV": te_profile,
        "stage_3_flux_used_Wb": stage_3_flux_used,
        "poloidal_beta": beta_p_profile,
        "Bv_required_T": bv_required,
        "pf_balance_residual": pf_result["pf_balance_residual"],
        "x_point_residual": x_point_residual,
        "strike_point_residual": div_result["strike_point_residual"],
        "vs_reserved_fraction": [float(strategy["vs_reserve"].get("reserve_fraction_of_limit", 0.70)) for _ in times],
    }
    rows = build_waveform_rows(
        times=times,
        ip_profile=ip_profile,
        loop_voltage=loop_voltage,
        flux_consumed=flux_consumed,
        flux_margin_fraction=flux_margin_fraction,
        shape_profile=shape_profile,
        x_point_profile=x_point_profile,
        strike_point_profile=strike_point_profile,
        q95_profile=q95_profile,
        internal_inductance=internal_inductance,
        vertical_margin=vertical_margin,
        cs_waveforms=cs_waveforms,
        pf_waveforms=pf_waveforms,
        div_waveforms=div_waveforms,
        vs_bias=vs_bias,
        total_available_flux_wb=total_available_flux,
        diagnostics=diagnostics,
    )

    end_state = extract_end_state(rows)
    shape_state = extract_shape_state(rows)
    divertor_state = extract_divertor_state(rows)
    final_flux_consumed = float(rows[-1]["flux_consumed_Wb"])
    final_flux_remaining = total_available_flux - final_flux_consumed
    final_flux_margin_fraction = final_flux_remaining / total_available_flux

    result = {
        "case_id": config["metadata"]["case_id"],
        "stage": "flattop",
        "flattop_waveform": rows,
        "summary": {
            "start_time_s": t_start,
            "end_time_s": t_end,
            "target_plasma_current_MA": float(targets["target_plasma_current_MA"]),
            "mean_plasma_current_MA": sum(float(row["Ip_MA"]) for row in rows) / len(rows),
            "max_loop_voltage_required_V": max(loop_voltage),
            "mean_loop_voltage_required_V": sum(loop_voltage) / len(loop_voltage),
            "stage_3_flux_consumed_Wb": final_flux_consumed - float(limits["flux"]["already_consumed_Wb"]),
            "total_flux_consumed_Wb": final_flux_consumed,
            "flux_remaining_Wb": final_flux_remaining,
            "flux_margin_fraction": final_flux_margin_fraction,
            "min_q95": min(q95_profile),
            "min_vertical_stability_margin": min(vertical_margin),
            "max_pf_balance_residual": max(pf_result["pf_balance_residual"]),
            "max_strike_point_residual": max(div_result["strike_point_residual"]),
        },
        "coil_state_at_flattop_end": {name: end_state[name] for name in ALL_COILS},
        "shape_state_at_flattop_end": shape_state,
        "auxiliary_settings": {
            "divertor_setting": divertor_state,
            "vs_reserved_range_kA": vs_reserved_range,
        },
        "final_state": {
            "time_s": float(rows[-1]["time_s"]),
            "plasma_current_MA": float(rows[-1]["Ip_MA"]),
            "loop_voltage_V": float(rows[-1]["loop_voltage_V"]),
            "flux_consumed_Wb": final_flux_consumed,
            "flux_remaining_Wb": final_flux_remaining,
            "flux_margin_fraction": final_flux_margin_fraction,
            "q95": float(rows[-1]["q95"]),
            "internal_inductance": float(rows[-1]["internal_inductance"]),
            "vertical_stability_margin": float(rows[-1]["vertical_stability_margin"]),
            "shape": shape_state,
            "divertor_setting": divertor_state,
            "vs_reserved_range_kA": vs_reserved_range,
            "coil_currents_kA": {name: end_state[name] for name in ALL_COILS},
            "physics_diagnostics": {
                "model": "minimum_physics_flattop_hold",
                "plasma_inductance_H": float(rows[-1]["plasma_inductance_H"]),
                "plasma_resistance_ohm": float(rows[-1]["plasma_resistance_ohm"]),
                "loop_voltage_required_V": float(rows[-1]["loop_voltage_required_V"]),
                "loop_voltage_cs_V": float(rows[-1]["loop_voltage_cs_V"]),
                "Bv_required_T": float(rows[-1]["Bv_required_T"]),
                "pf_balance_residual": float(rows[-1]["pf_balance_residual"]),
                "strike_point_residual": float(rows[-1]["strike_point_residual"]),
                "effective_cs_mutual_inductance_H": float(cs_result["effective_mutual_inductance_H"]),
            },
            "constraint_status": "pending_validation",
        },
    }

    validation = validate_flattop_result(config, result)
    result["flattop_validation"] = validation
    result["final_state"]["constraint_status"] = "passed" if validation["passed"] else "failed"
    result["revision_suggestions"] = _build_revision_suggestions(validation)
    return result


def write_outputs(result: dict[str, Any], output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> None:
    """写出 CSV、JSON 和 Markdown 摘要。"""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = result["flattop_waveform"]
    csv_path = out_dir / "flattop_waveform.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    json_path = out_dir / "flattop_waveform.json"
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    summary_path = out_dir / "flattop_summary.md"
    summary_path.write_text(_build_summary(result), encoding="utf-8")

    validation_path = out_dir / "flattop_validation.md"
    validation_path.write_text(_build_validation_report(result), encoding="utf-8")


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="Generate Stage 3 Flat-top candidate waveforms.")
    parser.add_argument("config", nargs="?", default=str(DEFAULT_CONFIG_PATH), help="Path to YAML config.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated outputs.")
    args = parser.parse_args()

    config = load_config(args.config)
    result = generate_flattop(config)
    write_outputs(result, args.output_dir)

    passed = result["flattop_validation"]["passed"]
    summary = result["summary"]
    print(f"Stage 3 Flat-top generated. validation_passed={passed}")
    print(f"Ip_mean_MA={summary['mean_plasma_current_MA']:.4f}")
    print(f"stage_3_flux_consumed_Wb={summary['stage_3_flux_consumed_Wb']:.4f}")
    print(f"flux_remaining_Wb={summary['flux_remaining_Wb']:.4f}")


def _initial_currents_from_handoff(handoff: dict[str, Any]) -> dict[str, float]:
    currents = handoff["coil_currents_kA"]
    result: dict[str, float] = {}
    for name in ALL_COILS:
        result[name] = float(currents.get(name, 0.0))
    return result


def _initial_shape_from_handoff(handoff: dict[str, Any]) -> dict[str, float]:
    shape = handoff.get("target_shape", {})
    return {
        "major_radius_m": float(shape.get("major_radius_m", 1.85)),
        "minor_radius_m": float(shape.get("minor_radius_m", 0.57)),
        "elongation": float(shape.get("elongation", 1.75)),
        "triangularity": float(shape.get("triangularity", 0.35)),
        "vertical_position_m": float(shape.get("vertical_position_m", 0.0)),
    }


def _x_point_residuals(x_point_profile: dict[str, list[float]], target_shape: dict[str, Any]) -> list[float]:
    lower = target_shape.get("x_point", {}).get("lower_x_point", {})
    r_target = float(lower.get("R_m", 1.55))
    z_target = float(lower.get("Z_m", -1.05))
    return [
        ((r - r_target) ** 2 + (z - z_target) ** 2) ** 0.5
        for r, z in zip(x_point_profile["lower_x_point_R_m"], x_point_profile["lower_x_point_Z_m"])
    ]


def _build_revision_suggestions(validation: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    for check in validation["checks"]:
        suggestion = check.get("suggestion", "")
        if not check["passed"] and suggestion and suggestion not in suggestions:
            suggestions.append(suggestion)
    if not suggestions:
        suggestions.append("当前 Flat-top 最小物理维持模型已通过简化验证，可继续与前三阶段结果拼接。")
    return suggestions


def _build_summary(result: dict[str, Any]) -> str:
    summary = result["summary"]
    end_state_lines = "\n".join(
        f"- `{name}`: {value:.4f} kA" for name, value in result["coil_state_at_flattop_end"].items()
    )
    shape_lines = "\n".join(
        f"- `{name}`: {value:.4f}" if isinstance(value, float) else f"- `{name}`: {value}"
        for name, value in result["shape_state_at_flattop_end"].items()
    )
    return f"""# Flat-top 阶段摘要

- 案例：`{result['case_id']}`
- 阶段：`flattop`
- 起始时间：`{summary['start_time_s']:.4f} s`
- 结束时间：`{summary['end_time_s']:.4f} s`
- 目标平台电流：`{summary['target_plasma_current_MA']:.4f} MA`
- 平均平台电流：`{summary['mean_plasma_current_MA']:.4f} MA`
- Stage 3 消耗伏秒：`{summary['stage_3_flux_consumed_Wb']:.4f} Wb`
- 总消耗伏秒：`{summary['total_flux_consumed_Wb']:.4f} Wb`
- 剩余伏秒：`{summary['flux_remaining_Wb']:.4f} Wb`
- 剩余伏秒比例：`{summary['flux_margin_fraction']:.4f}`
- 验证是否通过：`{result['flattop_validation']['passed']}`

## Flat-top 末态线圈电流

{end_state_lines}

## Flat-top 末态位形

{shape_lines}
"""


def _build_validation_report(result: dict[str, Any]) -> str:
    validation = result["flattop_validation"]
    lines = ["# Flat-top 验证报告", "", f"总体通过：`{validation['passed']}`", "", "## 检查项", ""]
    for check in validation["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- `{check['name']}`: {status}")
        if check["suggestion"]:
            lines.append(f"  - 建议：{check['suggestion']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
