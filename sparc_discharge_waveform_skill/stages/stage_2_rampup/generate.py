"""Ramp-up 阶段主入口。

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
    raise ImportError("Please install PyYAML before running stage_2_rampup.generate") from exc

try:
    from .models import (
        ALL_COILS,
        build_waveform_rows,
        compute_loop_voltage_terms,
        compute_plasma_inductance_profile,
        compute_required_vertical_field,
        estimate_flux_consumption,
        estimate_q95_profile_from_geometry,
        estimate_vertical_stability_margin,
        extract_end_state,
        extract_shape_state,
        generate_cs_waveforms_from_mutual_inductance,
        generate_density_profile,
        generate_div_waveforms,
        generate_internal_inductance_profile,
        generate_ip_profile,
        generate_pf_waveforms_from_response_matrix,
        generate_plasma_resistance_profile,
        generate_poloidal_beta_profile,
        generate_shape_profile,
        generate_temperature_profile,
        generate_vs_bias,
        make_time_axis,
    )
    from .validation import validate_config, validate_rampup_result
except ImportError:  # 允许直接 python generate.py 运行
    from models import (  # type: ignore
        ALL_COILS,
        build_waveform_rows,
        compute_loop_voltage_terms,
        compute_plasma_inductance_profile,
        compute_required_vertical_field,
        estimate_flux_consumption,
        estimate_q95_profile_from_geometry,
        estimate_vertical_stability_margin,
        extract_end_state,
        extract_shape_state,
        generate_cs_waveforms_from_mutual_inductance,
        generate_density_profile,
        generate_div_waveforms,
        generate_internal_inductance_profile,
        generate_ip_profile,
        generate_pf_waveforms_from_response_matrix,
        generate_plasma_resistance_profile,
        generate_poloidal_beta_profile,
        generate_shape_profile,
        generate_temperature_profile,
        generate_vs_bias,
        make_time_axis,
    )
    from validation import validate_config, validate_rampup_result  # type: ignore


DEFAULT_CONFIG_PATH = Path(__file__).with_name("example.yaml")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "outputs" / "stage_2_rampup"


def load_config(path: str | Path) -> dict[str, Any]:
    """读取 YAML 配置。"""

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("config file must contain a YAML mapping")
    return config


def generate_rampup(config: dict[str, Any]) -> dict[str, Any]:
    """生成 Ramp-up 阶段候选结果。"""

    validate_config(config)

    handoff = config["handoff_from_stage_1"]
    targets = config["targets"]
    strategy = config["waveform_strategy"]
    limits = config["engineering_limits"]

    t_start = float(handoff["time_s"])
    t_end = float(targets["end_time_s"])
    dt = float(strategy["time_grid"]["step_s"])
    times = make_time_axis(t_start, t_end, dt)

    ip_profile = generate_ip_profile(times, strategy["current_ramp"]["breakpoints"])
    initial_shape = _initial_shape_from_handoff(handoff)
    shape_profile = generate_shape_profile(times, initial_shape, targets["target_shape"])

    physics = config.get("physics", {})
    internal_inductance = generate_internal_inductance_profile(times, physics)
    electron_temperature = generate_temperature_profile(times, physics)
    plasma_resistance = generate_plasma_resistance_profile(times, physics)
    plasma_inductance = compute_plasma_inductance_profile(shape_profile, internal_inductance)
    loop_voltage_terms = compute_loop_voltage_terms(times, ip_profile, plasma_inductance, plasma_resistance)
    loop_voltage = loop_voltage_terms["loop_voltage_required_V"]
    flux_consumed = estimate_flux_consumption(times, loop_voltage, float(limits["flux"]["already_consumed_Wb"]))

    density_profile = generate_density_profile(times, strategy["density_ramp"])
    q95_profile = estimate_q95_profile_from_geometry(
        ip_profile,
        shape_profile,
        _device_b0_t(config),
        float(targets["target_q95"]),
    )
    poloidal_beta = generate_poloidal_beta_profile(times, physics)
    vertical_margin = estimate_vertical_stability_margin(shape_profile)
    bv_required = compute_required_vertical_field(ip_profile, shape_profile, internal_inductance, poloidal_beta)

    initial_currents = _initial_currents_from_handoff(handoff)
    cs_waveforms, loop_voltage_cs = generate_cs_waveforms_from_mutual_inductance(
        times,
        initial_currents,
        loop_voltage,
        physics,
    )
    pf_waveforms, pf_balance_residual = generate_pf_waveforms_from_response_matrix(
        times,
        initial_currents,
        shape_profile,
        bv_required,
        physics,
    )
    div_waveforms = generate_div_waveforms(times, initial_currents)
    vs_bias = generate_vs_bias(times, initial_currents)

    total_available_flux = float(limits["flux"]["total_available_Wb"])
    flux_remaining = [total_available_flux - value for value in flux_consumed]
    stage_flux_start = float(limits["flux"]["already_consumed_Wb"])
    physics_diagnostics = {
        "plasma_inductance_H": plasma_inductance,
        "plasma_resistance_ohm": plasma_resistance,
        "electron_temperature_eV": electron_temperature,
        "loop_voltage_required_V": loop_voltage,
        "loop_voltage_cs_V": loop_voltage_cs,
        "loop_voltage_inductive_V": loop_voltage_terms["loop_voltage_inductive_V"],
        "loop_voltage_resistive_V": loop_voltage_terms["loop_voltage_resistive_V"],
        "cs_flux_used_stage_Wb": [value - stage_flux_start for value in flux_consumed],
        "cs_flux_remaining_Wb": flux_remaining,
        "poloidal_beta": poloidal_beta,
        "Bv_required_T": bv_required,
        "pf_balance_residual": pf_balance_residual,
        "vs_reserved_fraction": [float(config.get("control_constraints", {}).get("vs_reserved_fraction", 0.20)) for _ in times],
    }

    rows = build_waveform_rows(
        times=times,
        ip_profile=ip_profile,
        loop_voltage=loop_voltage,
        flux_consumed=flux_consumed,
        shape_profile=shape_profile,
        density_profile=density_profile,
        q95_profile=q95_profile,
        internal_inductance=internal_inductance,
        vertical_margin=vertical_margin,
        cs_waveforms=cs_waveforms,
        pf_waveforms=pf_waveforms,
        div_waveforms=div_waveforms,
        vs_bias=vs_bias,
        physics_diagnostics=physics_diagnostics,
    )

    end_state = extract_end_state(rows)
    shape_state = extract_shape_state(rows)
    handoff_to_stage_3 = {
        "time_s": float(rows[-1]["time_s"]),
        "plasma_current_MA": float(rows[-1]["Ip_MA"]),
        "loop_voltage_V": float(rows[-1]["loop_voltage_V"]),
        "flux_consumed_Wb": float(rows[-1]["flux_consumed_Wb"]),
        "flux_remaining_Wb": float(rows[-1]["cs_flux_remaining_Wb"]),
        "cs_flux_remaining_after_rampup_Vs": float(rows[-1]["cs_flux_remaining_Wb"]),
        "q95": float(rows[-1]["q95"]),
        "internal_inductance": float(rows[-1]["internal_inductance"]),
        "vertical_stability_margin": float(rows[-1]["vertical_stability_margin"]),
        "target_shape": shape_state,
        "coil_currents_kA": {name: end_state[name] for name in ALL_COILS},
        "physics_diagnostics": {
            "loop_voltage_required_V": float(rows[-1]["loop_voltage_required_V"]),
            "loop_voltage_cs_V": float(rows[-1]["loop_voltage_cs_V"]),
            "plasma_inductance_H": float(rows[-1]["plasma_inductance_H"]),
            "plasma_resistance_ohm": float(rows[-1]["plasma_resistance_ohm"]),
            "Bv_required_T": float(rows[-1]["Bv_required_T"]),
            "pf_balance_residual": float(rows[-1]["pf_balance_residual"]),
        },
        "constraint_status": "pending_validation",
    }

    result = {
        "case_id": config["metadata"]["case_id"],
        "stage": "rampup",
        "rampup_waveform": rows,
        "summary": {
            "start_time_s": t_start,
            "end_time_s": t_end,
            "start_plasma_current_MA": float(rows[0]["Ip_MA"]),
            "end_plasma_current_MA": float(rows[-1]["Ip_MA"]),
            "stage_2_flux_consumed_Wb": float(rows[-1]["cs_flux_used_stage_Wb"]),
            "total_flux_consumed_Wb": float(rows[-1]["flux_consumed_Wb"]),
            "flux_remaining_Wb": handoff_to_stage_3["flux_remaining_Wb"],
            "max_loop_voltage_required_V": max(float(row["loop_voltage_required_V"]) for row in rows),
            "max_loop_voltage_tracking_error_V": max(abs(float(row["loop_voltage_required_V"]) - float(row["loop_voltage_cs_V"])) for row in rows),
            "min_q95": min(float(row["q95"]) for row in rows),
            "min_vertical_stability_margin": min(float(row["vertical_stability_margin"]) for row in rows),
            "max_pf_balance_residual": max(float(row["pf_balance_residual"]) for row in rows),
        },
        "coil_state_at_rampup_end": {name: end_state[name] for name in ALL_COILS},
        "shape_state_at_rampup_end": shape_state,
        "physics_diagnostics": {
            "model": "minimal_rampup_physics_constraints",
            "uses_plasma_circuit_equation": True,
            "uses_cs_mutual_inductance": True,
            "uses_pf_response_matrix": True,
        },
        "cs_flux_remaining_after_rampup_Wb": handoff_to_stage_3["flux_remaining_Wb"],
        "handoff_to_stage_3": handoff_to_stage_3,
    }

    validation = validate_rampup_result(config, result)
    result["rampup_validation"] = validation
    result["handoff_to_stage_3"]["constraint_status"] = "passed" if validation["passed"] else "failed"
    return result


def write_outputs(result: dict[str, Any], output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> None:
    """写出 CSV、JSON 和 Markdown 摘要。"""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = result["rampup_waveform"]
    csv_path = out_dir / "rampup_waveform.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    json_path = out_dir / "rampup_waveform.json"
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    summary_path = out_dir / "rampup_summary.md"
    summary_path.write_text(_build_summary(result), encoding="utf-8")

    validation_path = out_dir / "rampup_validation.md"
    validation_path.write_text(_build_validation_report(result), encoding="utf-8")


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="Generate Stage 2 Ramp-up candidate waveforms.")
    parser.add_argument("config", nargs="?", default=str(DEFAULT_CONFIG_PATH), help="Path to YAML config.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated outputs.")
    args = parser.parse_args()

    config = load_config(args.config)
    result = generate_rampup(config)
    write_outputs(result, args.output_dir)

    passed = result["rampup_validation"]["passed"]
    summary = result["summary"]
    print(f"Stage 2 Ramp-up generated. validation_passed={passed}")
    print(f"Ip_end_MA={summary['end_plasma_current_MA']:.4f}")
    print(f"stage_2_flux_consumed_Wb={summary['stage_2_flux_consumed_Wb']:.4f}")
    print(f"flux_remaining_Wb={summary['flux_remaining_Wb']:.4f}")


def _initial_currents_from_handoff(handoff: dict[str, Any]) -> dict[str, float]:
    currents = handoff["coil_currents_kA"]
    result: dict[str, float] = {}
    for name in ALL_COILS:
        result[name] = float(currents.get(name, 0.0))
    return result


def _device_b0_t(config: dict[str, Any]) -> float:
    device = config.get("device", {})
    return float(device.get("B0_T", 12.2))


def _initial_shape_from_handoff(handoff: dict[str, Any]) -> dict[str, float]:
    plasma_state = handoff.get("plasma_state", {})
    return {
        "major_radius_m": float(plasma_state.get("major_radius_m", 1.85)),
        "minor_radius_m": float(plasma_state.get("minor_radius_m", 0.35)),
        "elongation": float(plasma_state.get("elongation", 1.15)),
        "triangularity": float(plasma_state.get("triangularity", 0.05)),
        "vertical_position_m": float(plasma_state.get("vertical_position_m", 0.0)),
    }


def _build_summary(result: dict[str, Any]) -> str:
    summary = result["summary"]
    end_state_lines = "\n".join(
        f"- `{name}`: {value:.4f} kA" for name, value in result["coil_state_at_rampup_end"].items()
    )
    shape_lines = "\n".join(
        f"- `{name}`: {value:.4f}" for name, value in result["shape_state_at_rampup_end"].items()
    )
    return f"""# Ramp-up 阶段摘要

- 案例：`{result['case_id']}`
- 阶段：`rampup`
- 起始时间：`{summary['start_time_s']:.4f} s`
- 结束时间：`{summary['end_time_s']:.4f} s`
- 起始 Ip：`{summary['start_plasma_current_MA']:.4f} MA`
- 末端 Ip：`{summary['end_plasma_current_MA']:.4f} MA`
- Stage 2 消耗伏秒：`{summary['stage_2_flux_consumed_Wb']:.4f} Wb`
- 总消耗伏秒：`{summary['total_flux_consumed_Wb']:.4f} Wb`
- 剩余伏秒：`{summary['flux_remaining_Wb']:.4f} Wb`
- 最大物理环电压需求：`{summary['max_loop_voltage_required_V']:.4f} V`
- 最大 CS 环电压跟踪误差：`{summary['max_loop_voltage_tracking_error_V']:.4f} V`
- 最小 q95：`{summary['min_q95']:.4f}`
- 最小垂直稳定裕度：`{summary['min_vertical_stability_margin']:.4f}`
- 最大 PF 平衡残差：`{summary['max_pf_balance_residual']:.6f}`
- 验证是否通过：`{result['rampup_validation']['passed']}`

## Ramp-up 末态线圈电流

{end_state_lines}

## Ramp-up 末态位形

{shape_lines}
"""


def _build_validation_report(result: dict[str, Any]) -> str:
    validation = result["rampup_validation"]
    lines = ["# Ramp-up 验证报告", "", f"总体通过：`{validation['passed']}`", "", "## 检查项", ""]
    for check in validation["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- `{check['name']}`: {status}")
        if check["suggestion"]:
            lines.append(f"  - 建议：{check['suggestion']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
