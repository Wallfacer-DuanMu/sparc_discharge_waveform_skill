"""Breakdown 阶段主入口。

职责：读取输入配置，调用 models.py 生成候选波形，再调用 validation.py 完成检查。
本文件保持为流程编排层，不把模型和验证细节混在一起。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - 运行环境缺少依赖时给出清晰提示
    raise ImportError("Please install PyYAML before running stage_1_breakdown.generate") from exc

try:
    from .models import (
        ALL_COILS,
        PF_COILS,
        build_waveform_rows,
        estimate_cs_flux_used,
        estimate_zero_field_error,
        extract_end_state,
        generate_cs_swing,
        generate_hold_waveforms,
        generate_ip_seed_profile,
        generate_pf_null_preset,
        make_time_axis,
    )
    from .validation import validate_breakdown_result, validate_config
except ImportError:  # 允许直接 python generate.py 运行
    from models import (  # type: ignore
        ALL_COILS,
        PF_COILS,
        build_waveform_rows,
        estimate_cs_flux_used,
        estimate_zero_field_error,
        extract_end_state,
        generate_cs_swing,
        generate_hold_waveforms,
        generate_ip_seed_profile,
        generate_pf_null_preset,
        make_time_axis,
    )
    from validation import validate_breakdown_result, validate_config  # type: ignore


DEFAULT_CONFIG_PATH = Path(__file__).with_name("example.yaml")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "outputs" / "stage_1_breakdown"


def load_config(path: str | Path) -> dict[str, Any]:
    """读取 YAML 配置。"""

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("config file must contain a YAML mapping")
    return config


def generate_breakdown(config: dict[str, Any]) -> dict[str, Any]:
    """生成 Breakdown 阶段候选结果。"""

    validate_config(config)

    timeline = config["timeline"]
    target = config["target"]
    coils = config["coils"]
    constraints = config["constraints"]
    options = config["options"]

    t_start = float(timeline["t_start_s"])
    t_end = float(timeline["breakdown_end_s"])
    dt = float(timeline["dt_s"])
    loop_voltage_v = float(constraints["breakdown_loop_voltage_V"])

    times = make_time_axis(t_start, t_end, dt)
    ip_profile = generate_ip_seed_profile(times, float(target["Ip_seed_MA"]))
    cs_flux_used = estimate_cs_flux_used(loop_voltage_v, t_start, t_end)

    cs_waveforms = generate_cs_swing(
        times=times,
        coils=coils,
        share=options.get("cs_swing_share", {"CS1": 0.30, "CS2": 0.40, "CS3": 0.30}),
        loop_voltage_v=loop_voltage_v,
    )
    pf_waveforms = generate_pf_null_preset(
        times=times,
        coils=coils,
        targets=options.get("pf_null_preset_target_MA", {}),
    )
    aux_waveforms = generate_hold_waveforms(times, coils)

    rows = build_waveform_rows(
        times=times,
        ip_profile=ip_profile,
        cs_waveforms=cs_waveforms,
        pf_waveforms=pf_waveforms,
        aux_waveforms=aux_waveforms,
        b0_t=float(config["device"]["B0_T"]),
    )

    end_state = extract_end_state(rows)
    pf_end_state = {name: end_state[name] for name in PF_COILS}
    zero_field_error = estimate_zero_field_error(pf_end_state)
    cs_budget = float(constraints["cs_flux_budget_Vs"])
    validation = validate_breakdown_result(config, rows, cs_flux_used, zero_field_error)

    return {
        "case_name": config["case_name"],
        "stage": "breakdown",
        "breakdown_waveform": rows,
        "Ip_at_breakdown_end_MA": float(rows[-1]["Ip_MA"]),
        "coil_state_at_breakdown_end": {name: end_state[name] for name in ALL_COILS},
        "cs_flux_used_breakdown_Vs": cs_flux_used,
        "cs_flux_remaining_after_breakdown_Vs": cs_budget - cs_flux_used,
        "zero_field_error_T": zero_field_error,
        "breakdown_validation": validation,
    }


def write_outputs(result: dict[str, Any], output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> None:
    """写出 CSV、JSON 和 Markdown 摘要。"""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = result["breakdown_waveform"]
    csv_path = out_dir / "breakdown_waveform.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    json_path = out_dir / "breakdown_waveform.json"
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    summary_path = out_dir / "breakdown_summary.md"
    summary_path.write_text(_build_summary(result), encoding="utf-8")

    validation_path = out_dir / "breakdown_validation.md"
    validation_path.write_text(_build_validation_report(result), encoding="utf-8")


def main() -> None:
    """命令行入口。"""

    parser = argparse.ArgumentParser(description="Generate Stage 1 Breakdown candidate waveforms.")
    parser.add_argument("config", nargs="?", default=str(DEFAULT_CONFIG_PATH), help="Path to YAML config.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated outputs.")
    args = parser.parse_args()

    config = load_config(args.config)
    result = generate_breakdown(config)
    write_outputs(result, args.output_dir)

    passed = result["breakdown_validation"]["passed"]
    print(f"Stage 1 Breakdown generated. validation_passed={passed}")
    print(f"Ip_at_breakdown_end_MA={result['Ip_at_breakdown_end_MA']:.4f}")
    print(f"cs_flux_used_breakdown_Vs={result['cs_flux_used_breakdown_Vs']:.4f}")
    print(f"zero_field_error_T={result['zero_field_error_T']:.6f}")


def _build_summary(result: dict[str, Any]) -> str:
    end_state_lines = "\n".join(
        f"- `{name}`: {value:.4f} MA" for name, value in result["coil_state_at_breakdown_end"].items()
    )
    return f"""# Breakdown 阶段摘要

- 案例：`{result['case_name']}`
- 阶段：`breakdown`
- 击穿末端 Ip：`{result['Ip_at_breakdown_end_MA']:.4f} MA`
- CS 已用伏秒：`{result['cs_flux_used_breakdown_Vs']:.4f} Vs`
- CS 剩余伏秒：`{result['cs_flux_remaining_after_breakdown_Vs']:.4f} Vs`
- 零场误差估计：`{result['zero_field_error_T']:.6f} T`
- 验证是否通过：`{result['breakdown_validation']['passed']}`

## 击穿末态线圈电流

{end_state_lines}
"""


def _build_validation_report(result: dict[str, Any]) -> str:
    validation = result["breakdown_validation"]
    lines = ["# Breakdown 验证报告", "", f"总体通过：`{validation['passed']}`", "", "## 检查项", ""]
    for check in validation["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- `{check['name']}`: {status}")
        if check["suggestion"]:
            lines.append(f"  - 建议：{check['suggestion']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
