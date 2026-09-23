"""
pytest設定とテストフィクスチャの定義
"""
import sys
from pathlib import Path
import pytest
import pandas

# プロジェクトルートをPythonパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def temp_test_dir(tmp_path):
    """一時的なテストディレクトリを作成"""
    test_dir = tmp_path / "test_session"
    test_dir.mkdir()
    return test_dir


@pytest.fixture
def sample_gt_csv(tmp_path):
    """サンプルの正解データCSVファイルを作成"""
    csv_path = tmp_path / "ground_truth" / "sample.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    df = pandas.DataFrame({
        "資産番号": ["A001", "A002", "A003"],
        "資産名称": ["パソコン", "机", "椅子"],
        "取得価額": ["100000", "50000", "30000"]
    })
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


@pytest.fixture
def sample_pd_csv_perfect_match(tmp_path):
    """正解データと完全一致する予測データCSVファイルを作成"""
    csv_path = tmp_path / "prediction" / "sample.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    df = pandas.DataFrame({
        "資産番号": ["A001", "A002", "A003"],
        "資産名称": ["パソコン", "机", "椅子"],
        "取得価額": ["100000", "50000", "30000"]
    })
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


@pytest.fixture
def sample_pd_csv_with_errors(tmp_path):
    """エラーを含む予測データCSVファイルを作成"""
    csv_path = tmp_path / "prediction" / "sample_error.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    df = pandas.DataFrame({
        "資産番号": ["A001", "A002", "A999"],  # A003 -> A999 (誤り)
        "資産名称": ["パソコン", "机", "椅子"],
        "取得価額": ["100000", "50000", "99999"]  # 30000 -> 99999 (誤り)
    })
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


@pytest.fixture
def sample_pd_csv_with_extra_column(tmp_path):
    """過剰列を含む予測データCSVファイルを作成"""
    csv_path = tmp_path / "prediction" / "sample_extra_col.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    df = pandas.DataFrame({
        "資産番号": ["A001", "A002", "A003"],
        "ゴミ列": ["XXX", "YYY", "ZZZ"],  # 過剰列
        "資産名称": ["パソコン", "机", "椅子"],
        "取得価額": ["100000", "50000", "30000"]
    })
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


@pytest.fixture
def sample_pd_csv_with_extra_row(tmp_path):
    """過剰行を含む予測データCSVファイルを作成"""
    csv_path = tmp_path / "prediction" / "sample_extra_row.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    df = pandas.DataFrame({
        "資産番号": ["A001", "A002", "A003", "EXTRA"],  # 過剰行
        "資産名称": ["パソコン", "机", "椅子", "不要"],
        "取得価額": ["100000", "50000", "30000", "99999"]
    })
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


@pytest.fixture
def sample_config_toml(tmp_path):
    """サンプルのconfig.tomlファイルを作成"""
    config_path = tmp_path / "config.toml"

    gt_dir = tmp_path / "ground_truth"
    pd_dir = tmp_path / "prediction"
    gt_dir.mkdir(exist_ok=True)
    pd_dir.mkdir(exist_ok=True)

    content = f"""[fal]
prediction_dir = "{str(pd_dir).replace(chr(92), chr(92)*2)}"
ground_truth_dir = "{str(gt_dir).replace(chr(92), chr(92)*2)}"
"""
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)

    return config_path
