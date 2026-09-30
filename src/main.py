#!/usr/bin/env python3

# standard library
import argparse
import logging
import re
import shutil
from pathlib import Path
import tomllib
# third-party
import pandas
# local
from src.eval.csv4db_evaluator import Csv4dbEvaluator
from src.utils import pathutils
from src.utils import cmd_executer
from src.utils import fileutils
from src.utils.pdf_statement_splitter import split_pdf_for_airead, consolidate_airead_outputs

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
    {
        "flags": ["-t", "--target_pdfs"],
        "kwargs": {"type": str, "help": "PDF numbers to process, e.g. 208 or 208,227 or 231-240."}
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



def parse_target_pdfs(value: str | None) -> set[str]:
    """Parse '208,227,231-240' into a set of company/PDF numbers."""
    if not value:
        return set()
    result: set[str] = set()
    for token in re.split(r"[,、\s]+", value.strip()):
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"指定PDFの形式が不正です: {token}")
            start, end = int(a), int(b)
            if start > end:
                start, end = end, start
            result.update(str(n) for n in range(start, end + 1))
        elif token.isdigit():
            result.add(str(int(token)))
        else:
            raise ValueError(f"指定PDFの形式が不正です: {token}")
    return result


def _company_no(name: str) -> str | None:
    m = re.search(r"(?:株式会社|#U682a#U5f0f#U4f1a#U793e)(\d+)", name, re.IGNORECASE)
    return str(int(m.group(1))) if m else None


def prepare_airead_input(batch_file: Path, target_pdfs: set[str]) -> dict:
    """Build input_work BEFORE launching AIRead.

    run_assort.bat no longer chooses/copies an input directory.  This makes the
    Python selection the single source of truth and prevents a specified run
    from accidentally falling back to the whole input folder.
    """
    source_dir = batch_file.parent / "input"
    work_dir = batch_file.parent / "input_work"
    pathutils.validate_dir(source_dir)

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    manifest: dict = {}
    matched_originals: list[str] = []

    for src in source_dir.iterdir():
        if not src.is_file():
            continue
        company = _company_no(src.name)
        if target_pdfs and company not in target_pdfs:
            continue

        matched_originals.append(src.name)
        if src.suffix.lower() == ".pdf":
            # 指定PDFは3方式を自動試行。全量は処理時間を抑えるため優先方式1つで分割する。
            manifest.update(split_pdf_for_airead(src, work_dir, robust=bool(target_pdfs)))
        else:
            shutil.copy2(src, work_dir / src.name)

    if target_pdfs and not matched_originals:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise FileNotFoundError(
            "指定PDFが input に見つかりません: " + ", ".join(sorted(target_pdfs, key=int))
        )

    prepared = [p for p in work_dir.iterdir() if p.is_file()]
    if not prepared:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError("AIReadへ渡すファイルが0件です。")

    # Fail fast: specified mode must contain ONLY requested company numbers.
    if target_pdfs:
        wrong = []
        for p in prepared:
            company = _company_no(p.name)
            if company not in target_pdfs:
                wrong.append(p.name)
        if wrong:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise RuntimeError("指定外PDFが input_work に混入しました: " + ", ".join(wrong))

        logging.info("🎯 指定PDFモード: %s", ", ".join(sorted(target_pdfs, key=int)))
        for name in matched_originals:
            logging.info("  元PDF: %s", name)
        logging.info("🔒 AIRead投入前チェックOK: input_work は指定PDFだけ (%dファイル)", len(prepared))
    else:
        logging.info("📚 全部モード: input_work に %dファイル準備", len(prepared))

    return manifest


def exec_airead(batch_file: Path, target_pdfs: set[str]) -> None:
    manifest = prepare_airead_input(batch_file, target_pdfs)
    # 前回実行のCSV/sidecarを今回の結果として拾わない。指定PDF時は対象会社だけ削除する。
    output_dir = batch_file.parent / "output"
    if output_dir.exists():
        for old in output_dir.glob("*.csv"):
            company = _company_no(old.name)
            if not target_pdfs or company in target_pdfs:
                try: old.unlink()
                except OSError: pass
        sidecar = output_dir / ".logical_region_formids.json"
        if sidecar.exists():
            try: sidecar.unlink()
            except OSError: pass
    try:
        rc = cmd_executer.exec_batch(
            batch_file,
            cwd=batch_file.parent,
            popen_encoding='utf-8',
            stdout_encoding='utf-8'
        )
        # run_assort.bat はAIReadの部分失敗を0で返す。
        # ここでは成功した分割領域CSVを必ず物理ページへ統合してから評価する。
        if manifest:
            try:
                consolidate_airead_outputs(batch_file.parent / "output", manifest)
            except Exception:
                # 統合できる出力すら無い場合だけ本当の失敗として止める。
                if rc not in (0, None):
                    raise RuntimeError(
                        f"AIReadバッチが異常終了し、分割結果も統合できませんでした (Exit Code: {rc})"
                    )
                raise

        if rc not in (0, None):
            # Exit Code 5 でも、上で分割結果を正常に統合できたなら評価を続行する。
            logging.warning(
                "⚠ AIRead Exit Code %s（未分類領域あり）。成功した帳票は統合済みなので評価を続行します。",
                rc,
            )
    finally:
        # Normally run_assort.bat removes it. Clean leftovers after errors too.
        work_dir = batch_file.parent / "input_work"
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

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
    target_pdfs = parse_target_pdfs(args.target_pdfs)

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
                exec_airead(airead_batch_file, target_pdfs)

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
            exec_airead(airead_batch_file, target_pdfs)

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
    