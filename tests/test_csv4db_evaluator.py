"""
FalEvaluator クラスのユニットテスト
"""
import pytest
import pandas
from src.eval.csv4db_evaluator import Csv4dbEvaluator


class TestCsv4dbEvaluatorInit:
    """Csv4dbEvaluatorの初期化テスト"""

    def test_initialization_creates_session_dir(self, tmp_path):
        """初期化時にセッションディレクトリが作成されることを確認"""
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        evaluator = Csv4dbEvaluator(
            session="test",
            prediction_dir=pd_dir,
            ground_truth_dir=gt_dir,
            results_base_dir=results_dir
        )

        assert evaluator.session_dir.exists()
        assert evaluator.session_dir.is_dir()
        assert evaluator.session_dir.name == "test"

    def test_initialization_clears_existing_session_dir(self, tmp_path):
        """初期化時に既存のセッションディレクトリがクリアされることを確認"""
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()
        session_dir = results_dir / "test"
        session_dir.mkdir(parents=True)

        # 既存ファイルを作成
        old_file = session_dir / "old_file.txt"
        old_file.write_text("old content")

        evaluator = Csv4dbEvaluator(
            session="test",
            prediction_dir=pd_dir,
            ground_truth_dir=gt_dir,
            results_base_dir=results_dir
        )

        # 古いファイルが削除されていることを確認
        assert not old_file.exists()
        assert evaluator.session_dir.exists()


class TestNormalizeText:
    """_normalize_text静的メソッドのテスト"""

    def test_removes_special_characters(self):
        """特殊文字が削除されることを確認"""
        text = "テスト【重要】(注意)※1"
        result = Csv4dbEvaluator._normalize_text(text)
        assert result == "テスト重要注意1"

    def test_removes_whitespace(self):
        """空白文字が削除されることを確認"""
        text = "テスト　文字列  \t\n"
        result = Csv4dbEvaluator._normalize_text(text)
        assert result == "テスト文字列"

    def test_empty_string(self):
        """空文字列の処理を確認"""
        result = Csv4dbEvaluator._normalize_text("")
        assert result == ""


class TestGetSimilarity:
    """_get_similarity静的メソッドのテスト"""

    def test_identical_strings_return_1(self):
        """同一文字列は類似度1.0を返すことを確認"""
        result = Csv4dbEvaluator._get_similarity("test", "test")
        assert result == 1.0

    def test_completely_different_strings_return_0(self):
        """全く異なる文字列は類似度0.0を返すことを確認"""
        result = Csv4dbEvaluator._get_similarity("abc", "xyz")
        assert result == 0.0

    def test_similar_strings_return_high_score(self):
        """類似した文字列は高い類似度を返すことを確認"""
        result = Csv4dbEvaluator._get_similarity("test", "text")
        assert 0.5 < result < 1.0

    def test_substring_returns_high_score(self):
        """部分文字列は高い類似度を返すことを確認"""
        result = Csv4dbEvaluator._get_similarity("test", "testing")
        assert result >= 0.8


class TestCalcDataAccuracyByRow:
    """_calc_data_accuracy_by_row静的メソッドのテスト"""

    def test_perfect_match_returns_100_percent(self):
        """完全一致は100%の精度を返すことを確認"""
        row = pandas.Series({
            'c0_gt': 'A001',
            'c0_pd': 'A001',
            'c1_gt': '100000',
            'c1_pd': '100000'
        })

        result = Csv4dbEvaluator._calc_data_accuracy_by_row(row)

        # 戻り値はSeries([item_count, match_count, accuracy])
        assert result[0] == 2  # item_count
        assert result[1] == 2  # match_count
        assert result[2] == 100.0  # accuracy

    def test_partial_match_returns_correct_percentage(self):
        """部分一致は正しい精度を返すことを確認"""
        row = pandas.Series({
            'c0_gt': 'A001',
            'c0_pd': 'A001',
            'c1_gt': '100000',
            'c1_pd': '99999',  # 不一致
            'c2_gt': '200000',
            'c2_pd': '200000'
        })

        result = Csv4dbEvaluator._calc_data_accuracy_by_row(row)

        # 戻り値はSeries([item_count, match_count, accuracy])
        assert result[0] == 3  # item_count
        assert result[1] == 2  # match_count
        assert result[2] == pytest.approx(66.67, abs=0.01)  # accuracy

    def test_no_match_returns_0_percent(self):
        """全く一致しない場合は0%の精度を返すことを確認"""
        row = pandas.Series({
            'c0_gt': 'A001',
            'c0_pd': 'B999',
            'c1_gt': '100000',
            'c1_pd': '99999'
        })

        result = Csv4dbEvaluator._calc_data_accuracy_by_row(row)

        # 戻り値はSeries([item_count, match_count, accuracy])
        assert result[0] == 2  # item_count
        assert result[1] == 0  # match_count
        assert result[2] == 0.0  # accuracy

    def test_empty_gt_values_are_ignored(self):
        """空のGT値は計算から除外されることを確認"""
        row = pandas.Series({
            'c0_gt': '',
            'c0_pd': 'A001',
            'c1_gt': '100000',
            'c1_pd': '100000'
        })

        result = Csv4dbEvaluator._calc_data_accuracy_by_row(row)

        # 戻り値はSeries([item_count, match_count, accuracy])
        assert result[0] == 1  # item_count (空のGTは除外)
        assert result[1] == 1  # match_count


class TestLoadCsvToDataframe:
    """_load_csv_to_dataframe メソッドのテスト"""

    def test_loads_valid_csv_files(self, tmp_path):
        """有効なCSVファイルが正しく読み込まれることを確認"""
        gt_dir = tmp_path / "gt"
        pd_dir = tmp_path / "pd"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        # CSVファイル作成
        gt_file = gt_dir / "test.csv"
        pd_file = pd_dir / "test.csv"

        pandas.DataFrame({"col1": ["A", "B"]}).to_csv(gt_file, index=False, encoding="utf-8-sig")
        pandas.DataFrame({"col1": ["A", "B"]}).to_csv(pd_file, index=False, encoding="utf-8-sig")

        evaluator = Csv4dbEvaluator(
            session="test",
            prediction_dir=pd_dir,
            ground_truth_dir=gt_dir,
            results_base_dir=results_dir
        )

        gt_df, pd_df = evaluator._load_csv_to_dataframe(gt_file, pd_file)

        assert gt_df is not None
        assert pd_df is not None
        assert len(gt_df) == 2
        assert len(pd_df) == 2

    def test_returns_none_for_invalid_file(self, tmp_path):
        """無効なファイルではNoneを返すことを確認"""
        gt_dir = tmp_path / "gt"
        pd_dir = tmp_path / "pd"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        gt_file = gt_dir / "nonexistent.csv"
        pd_file = pd_dir / "nonexistent.csv"

        evaluator = Csv4dbEvaluator(
            session="test",
            prediction_dir=pd_dir,
            ground_truth_dir=gt_dir,
            results_base_dir=results_dir
        )

        gt_df, pd_df = evaluator._load_csv_to_dataframe(gt_file, pd_file)

        assert gt_df is None
        assert pd_df is None


class TestExtractDifferences:
    """_extract_differences メソッドのテスト"""

    def test_extracts_rows_with_less_than_100_accuracy(self, tmp_path):
        """精度100%未満の行が抽出されることを確認"""
        gt_dir = tmp_path / "gt"
        pd_dir = tmp_path / "pd"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        evaluator = Csv4dbEvaluator(
            session="test",
            prediction_dir=pd_dir,
            ground_truth_dir=gt_dir,
            results_base_dir=results_dir
        )

        test_df = pandas.DataFrame({
            'row_id': ['r1', 'r2', 'r3'],
            'accuracy': [100.0, 50.0, 100.0],
            'row_presence': ['both', 'both', 'both']
        })

        diff_df = evaluator._extract_differences(test_df)

        assert len(diff_df) == 1
        assert diff_df.iloc[0]['row_id'] == 'r2'

    def test_extracts_rows_with_presence_not_both(self, tmp_path):
        """row_presenceがbothでない行が抽出されることを確認"""
        gt_dir = tmp_path / "gt"
        pd_dir = tmp_path / "pd"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        evaluator = Csv4dbEvaluator(
            session="test",
            prediction_dir=pd_dir,
            ground_truth_dir=gt_dir,
            results_base_dir=results_dir
        )

        test_df = pandas.DataFrame({
            'row_id': ['r1', 'r2', 'r3'],
            'accuracy': [100.0, 100.0, 100.0],
            'row_presence': ['both', 'left_only', 'right_only']
        })

        diff_df = evaluator._extract_differences(test_df)

        assert len(diff_df) == 2
        assert 'r2' in diff_df['row_id'].values
        assert 'r3' in diff_df['row_id'].values


class TestCompareWithPandas:
    """compare_with_pandas メソッドの統合テスト"""

    def test_complete_workflow_with_matching_files(self, tmp_path):
        """完全一致ファイルでワークフロー全体が正常に動作することを確認"""
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        # 完全一致するCSVファイルを作成
        df = pandas.DataFrame({
            "資産番号": ["A001", "A002"],
            "資産名称": ["パソコン", "机"],
            "取得価額": ["100000", "50000"]
        })

        df.to_csv(gt_dir / "test.csv", index=False, encoding="utf-8-sig")
        df.to_csv(pd_dir / "test.csv", index=False, encoding="utf-8-sig")

        evaluator = Csv4dbEvaluator(
            session="test",
            prediction_dir=pd_dir,
            ground_truth_dir=gt_dir,
            results_base_dir=results_dir
        )

        # メインプロセス実行
        evaluator.compare_with_pandas()

        # サマリーレポートが生成されていることを確認
        summary_file = evaluator.session_dir / "summary_report.csv"
        assert summary_file.exists()

        # サマリー内容を確認
        summary_df = pandas.read_csv(summary_file)
        assert len(summary_df) == 1
        assert summary_df.iloc[0]['項目精度(%)'] == 100.0

    def test_workflow_with_mismatched_files(self, tmp_path):
        """不一致を含むファイルでワークフローが正常に動作することを確認"""
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        # 正解データ
        gt_df = pandas.DataFrame({
            "資産番号": ["A001", "A002"],
            "資産名称": ["パソコン", "机"],
            "取得価額": ["100000", "50000"]
        })

        # 予測データ（エラーを含む）
        pd_df = pandas.DataFrame({
            "資産番号": ["A001", "A999"],  # A002 -> A999
            "資産名称": ["パソコン", "机"],
            "取得価額": ["100000", "99999"]  # 50000 -> 99999
        })

        gt_df.to_csv(gt_dir / "test.csv", index=False, encoding="utf-8-sig")
        pd_df.to_csv(pd_dir / "test.csv", index=False, encoding="utf-8-sig")

        evaluator = Csv4dbEvaluator(
            session="test",
            prediction_dir=pd_dir,
            ground_truth_dir=gt_dir,
            results_base_dir=results_dir
        )

        # メインプロセス実行
        evaluator.compare_with_pandas()

        # サマリーレポートが生成されていることを確認
        summary_file = evaluator.session_dir / "summary_report.csv"
        assert summary_file.exists()

        # サマリー内容を確認（100%でないことを確認）
        summary_df = pandas.read_csv(summary_file)
        assert len(summary_df) == 1
        assert summary_df.iloc[0]['項目精度(%)'] < 100.0

        # 個別レポートが生成されていることを確認
        html_dir = evaluator.session_dir / "individual reports" / "html"
        csv_dir = evaluator.session_dir / "individual reports" / "csv" / "test"

        assert html_dir.exists()
        assert csv_dir.exists()
