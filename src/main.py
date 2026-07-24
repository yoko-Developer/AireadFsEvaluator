#!/usr/bin/env python3

# standard library
import argparse
import logging
from pathlib import Path
import tomllib
# third-party
import pandas
# local
from src.eval.csv4db_evaluator import Csv4dbEvaluator
from src.utils import pathutils
from src.utils import cmd_executer
from src.utils import fileutils

"""
OCR精度評価のmain()
"""

RESULTS_BASE_DIR: Path = pathutils.get_project_root_dir() / "results"

ARG_DEFS = [
    {
        "flags": ["-c", "--config_file"],
        "kwargs": {"type": Path, "help": "Path to the config file. If specified, other options will be ignored."}
    },
    {
        "flags": ["-A", "--airead_batch_file"],
        "kwargs": {"type": Path, "help": "Path to the AIRead batch file."}
    },
    {
        "flags": ["-s", "--session_type"],
        "kwargs": {"type": str, "help": "The AIRead session type. Used as an item name in whole summary report and as a folder name directly under the result folder. If -c is not specified, this option is required."}
    },
    {
        "flags": ["-g", "--ground_truth_dir"],
        "kwargs": {"type": Path, "help": "Dir that has ground truth file of AIRead. If -c is not specified, this option is required."}
    },
    {
        "flags": ["-p", "--prediction_dir"],
        "kwargs": {"type": Path, "help": "Output dir of AIRead. If -c is not specified, this option is required."}
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for arg in ARG_DEFS:
        parser.add_argument(*arg["flags"], **arg["kwargs"])
    return parser.parse_args()


def load_config(config_file: Path) -> dict:
    if not config_file.exists():
        raise FileNotFoundError("Config file not found")

    with open(config_file, "rb") as f:
        return tomllib.load(f)


def export_whole_summary_report():
    agged_summarys = []
    for path in RESULTS_BASE_DIR.glob("*/summary_report.csv"):
        df = pandas.read_csv(path, encoding=fileutils.detect_encoding(path))
        numeric_cols = df.select_dtypes(include='number').columns
        accuracy_cols = [col for col in numeric_cols if 'accuracy' in col.lower() or '精度' in col]
        sum_cols = [col for col in numeric_cols if col not in accuracy_cols]
        agg_df = pandas.DataFrame([df[sum_cols].sum()])
        for col in sum_cols:
            agg_df[col] = agg_df[col].astype(int)
        total_match = df['項目正解数'].sum() if '項目正解数' in df.columns else 0
        total_items = df['項目数'].sum() if '項目数' in df.columns else 0
        accuracy_value = round((total_match / total_items * 100), 2) if total_items > 0 else 0
        for col in accuracy_cols:
            agg_df[col] = accuracy_value
        agg_df = agg_df[[col for col in numeric_cols if col in agg_df.columns]]
        agg_df.insert(0, "帳票種別", path.parent.name)
        agged_summarys.append(agg_df)

    whole_summary = pandas.concat(agged_summarys, ignore_index=True) if agged_summarys else pandas.DataFrame()
    whole_summary.to_csv(RESULTS_BASE_DIR / "whole_summary_report.csv", index=False, encoding="utf-8-sig")

    logging.info(f"📊 Whole Summary Report Created: {RESULTS_BASE_DIR / 'whole_summary_report.csv'}")


def main():
    # 引数を解析
    args: argparse.Namespace = parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')

    if args.config_file is not None:
        logging.info(f"Loading config from: {args.config_file}")

        config = load_config(args.config_file)

        for section, content in config.items():
            if not content.get("ground_truth_dir"):
                logging.warning(f"Ground truth directory is required in section '{section}'.ground_truth_dir")
                continue
            if not content.get("prediction_dir"):
                logging.warning(f"Prediction directory is required in section '{section}'.prediction_dir")
                continue

            airead_batch_file: Path = Path(content.get("airead_batch_file")) if content.get("airead_batch_file") is not None else None
            ground_truth_dir: Path = Path(content.get("ground_truth_dir"))
            prediction_dir: Path = Path(content.get("prediction_dir"))

            pathutils.validate_dir(ground_truth_dir)
            pathutils.setup_dir(RESULTS_BASE_DIR)

            if airead_batch_file is not None:
                pathutils.validate_file(airead_batch_file)
                cmd_executer.exec_batch(airead_batch_file, cwd=airead_batch_file.parent, popen_encoding='utf-8', stdout_encoding='utf-8')

            pathutils.validate_dir(prediction_dir)

            if section is not None:
                evaluator = Csv4dbEvaluator(
                    session=section,
                    prediction_dir=prediction_dir,
                    ground_truth_dir=ground_truth_dir,
                    results_base_dir=RESULTS_BASE_DIR
                )
                evaluator.compare_with_pandas()
    else:
        logging.info("Using command-line arguments")

        if not args.ground_truth_dir:
            raise ValueError("Ground truth directory is required when not using a config file.")
        if not args.prediction_dir:
            raise ValueError("Prediction directory is required when not using a config file.")

        airead_batch_file = args.airead_batch_file
        ground_truth_dir = args.ground_truth_dir
        prediction_dir = args.prediction_dir
        session_type = args.session_type

        pathutils.validate_dir(ground_truth_dir)
        pathutils.setup_dir(RESULTS_BASE_DIR)

        if airead_batch_file is not None:
            pathutils.validate_file(airead_batch_file)
            cmd_executer.exec_batch(airead_batch_file, cwd=airead_batch_file.parent, popen_encoding='utf-8', stdout_encoding='utf-8')

        pathutils.validate_dir(prediction_dir)

        if session_type is not None:
            evaluator = Csv4dbEvaluator(
                session=session_type,
                prediction_dir=prediction_dir,
                ground_truth_dir=ground_truth_dir,
                results_base_dir=RESULTS_BASE_DIR
            )
            evaluator.compare_with_pandas()

    export_whole_summary_report()


if __name__ == "__main__":
    main()
    