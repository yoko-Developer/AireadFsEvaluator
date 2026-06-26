"""
main モジュールのユニットテスト
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas
from src import main


class TestParseArgs:
    """parse_args関数のテスト"""

    def test_parses_config_file_argument(self, monkeypatch):
        """config_fileオプションが正しく解析されることを確認"""
        test_args = ["-c", "test_config.toml"]
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)

        args = main.parse_args()

        assert args.config_file == Path("test_config.toml")

    def test_parses_command_line_arguments(self, monkeypatch):
        """コマンドライン引数が正しく解析されることを確認"""
        test_args = [
            "-s", "fal",
            "-g", "./ground_truth",
            "-p", "./prediction"
        ]
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)

        args = main.parse_args()

        assert args.session_type == "fal"
        assert args.ground_truth_dir == Path("./ground_truth")
        assert args.prediction_dir == Path("./prediction")


class TestLoadConfig:
    """load_config関数のテスト"""

    def test_loads_valid_toml_config(self, tmp_path):
        """有効なTOML設定ファイルを読み込むことを確認"""
        config_file = tmp_path / "config.toml"
        config_content = """
            [fal]
            prediction_dir = "C:\\\\AIRead\\\\output"
            ground_truth_dir = "./data/ground_truth/fal"
        """
        config_file.write_text(config_content, encoding="utf-8")

        config = main.load_config(config_file)

        assert "fal" in config
        assert config["fal"]["prediction_dir"] == "C:\\AIRead\\output"
        assert config["fal"]["ground_truth_dir"] == "./data/ground_truth/fal"

    def test_raises_error_for_nonexistent_file(self, tmp_path):
        """存在しないファイルで例外が発生することを確認"""
        nonexistent_file = tmp_path / "nonexistent.toml"

        with pytest.raises(FileNotFoundError) as exc_info:
            main.load_config(nonexistent_file)

        assert "Config file not found" in str(exc_info.value)


class TestExportWholeSummaryReport:
    """export_whole_summary_report関数のテスト"""

    def test_creates_whole_summary_report(self, tmp_path, monkeypatch):
        """全体サマリーレポートが正常に作成されることを確認"""
        # 一時的なresultsディレクトリを設定
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        # 複数のセッション結果を作成
        for session in ["fal_session1", "fal_session2"]:
            session_dir = results_dir / session
            session_dir.mkdir()

            summary_df = pandas.DataFrame({
                "ファイル名": ["test1.csv", "test2.csv"],
                "項目精度(%)": [95.5, 88.2],
                "項目正解数": [100, 80],
                "項目数": [105, 91]
            })
            summary_df.to_csv(session_dir / "summary_report.csv", index=False, encoding="utf-8-sig")

        # RESULTS_BASE_DIRを一時ディレクトリに設定
        monkeypatch.setattr("src.main.RESULTS_BASE_DIR", results_dir)

        # 関数実行
        main.export_whole_summary_report()

        # 全体サマリーファイルが作成されていることを確認
        whole_summary_file = results_dir / "whole_summary_report.csv"
        assert whole_summary_file.exists()

        # 内容を確認
        whole_df = pandas.read_csv(whole_summary_file)
        assert len(whole_df) == 2  # 2つのセッション
        assert "帳票種別" in whole_df.columns
        assert "項目精度(%)" in whole_df.columns

    def test_handles_empty_results_directory(self, tmp_path, monkeypatch):
        """結果ディレクトリが空の場合の処理を確認"""
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        # RESULTS_BASE_DIRを一時ディレクトリに設定
        monkeypatch.setattr("src.main.RESULTS_BASE_DIR", results_dir)

        # 関数実行（例外が発生しないことを確認）
        main.export_whole_summary_report()

        # 空のサマリーファイルが作成されることを確認
        whole_summary_file = results_dir / "whole_summary_report.csv"
        assert whole_summary_file.exists()


class TestMain:
    """main関数の統合テスト"""

    @patch("src.main.Csv4dbEvaluator")
    @patch("src.main.cmd_executer.exec_batch")
    def test_main_with_config_file(self, mock_exec_batch, mock_evaluator, tmp_path, monkeypatch):
        """config.tomlファイルを使用したmain関数の実行を確認"""
        # 設定ファイル作成
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        # ダミーCSVファイルを作成
        pandas.DataFrame({"col": ["val"]}).to_csv(gt_dir / "test.csv", index=False)
        pandas.DataFrame({"col": ["val"]}).to_csv(pd_dir / "test.csv", index=False)

        config_file = tmp_path / "test_config.toml"
        config_content = f"""
            [fal]
            prediction_dir = "{str(pd_dir).replace(chr(92), chr(92)*2)}"
            ground_truth_dir = "{str(gt_dir).replace(chr(92), chr(92)*2)}"
        """
        config_file.write_text(config_content, encoding="utf-8")

        # モックの設定
        mock_evaluator_instance = MagicMock()
        mock_evaluator.return_value = mock_evaluator_instance

        # RESULTS_BASE_DIRを一時ディレクトリに設定
        monkeypatch.setattr("src.main.RESULTS_BASE_DIR", results_dir)

        # コマンドライン引数の設定
        test_args = ["-c", str(config_file)]
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)

        # main関数実行
        main.main()

        # FalEvaluatorが呼び出されたことを確認
        mock_evaluator.assert_called_once()
        mock_evaluator_instance.compare_with_pandas.assert_called_once()

    @patch("src.main.Csv4dbEvaluator")
    def test_main_with_command_line_args(self, mock_evaluator, tmp_path, monkeypatch):
        """コマンドライン引数を使用したmain関数の実行を確認"""
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"

        gt_dir.mkdir()
        pd_dir.mkdir()

        # ダミーCSVファイルを作成
        pandas.DataFrame({"col": ["val"]}).to_csv(gt_dir / "test.csv", index=False)
        pandas.DataFrame({"col": ["val"]}).to_csv(pd_dir / "test.csv", index=False)

        # モックの設定
        mock_evaluator_instance = MagicMock()
        mock_evaluator.return_value = mock_evaluator_instance

        # RESULTS_BASE_DIRを一時ディレクトリに設定
        monkeypatch.setattr("src.main.RESULTS_BASE_DIR", results_dir)

        # コマンドライン引数の設定
        test_args = [
            "-s", "fal",
            "-g", str(gt_dir),
            "-p", str(pd_dir)
        ]
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)

        # main関数実行
        main.main()

        # FalEvaluatorが呼び出されたことを確認
        mock_evaluator.assert_called_once()
        mock_evaluator_instance.compare_with_pandas.assert_called_once()

    def test_main_raises_error_without_required_args(self, monkeypatch):
        """必須引数なしでエラーが発生することを確認"""
        # 不完全なコマンドライン引数の設定
        test_args = ["-s", "fal"]  # ground_truth_dirとprediction_dirが不足
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)

        # ValueError が発生することを確認
        with pytest.raises(ValueError) as exc_info:
            main.main()

        assert "Ground truth directory is required" in str(exc_info.value) or \
               "Prediction directory is required" in str(exc_info.value)

    def test_main_skips_section_with_missing_required_params(self, tmp_path, monkeypatch, caplog):
        """必須パラメータが欠けているセクションがスキップされることを確認"""
        # 不完全な設定ファイル作成
        config_file = tmp_path / "invalid_config.toml"
        config_content = """
            [fal]
            prediction_dir = "C:\\\\AIRead\\\\output"
            # ground_truth_dir が欠けている
        """
        config_file.write_text(config_content, encoding="utf-8")

        results_dir = tmp_path / "results"
        results_dir.mkdir()  # resultsディレクトリを事前に作成
        monkeypatch.setattr("src.main.RESULTS_BASE_DIR", results_dir)

        # コマンドライン引数の設定
        test_args = ["-c", str(config_file)]
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)

        # main関数実行（例外が発生しないことを確認）
        main.main()

        # 警告ログが出力されていることを確認
        assert "Ground truth directory is required" in caplog.text


class TestSessionTypeFlexibility:
    """session_typeの柔軟化に関するテスト"""
    
    def test_accepts_various_session_types(self, monkeypatch):
        """
        様々なセッションタイプが受け入れられることを確認
        """
        session_types = [
            "fal",           # 従来の値
            "bspl",          # 従来の値
            "invoice",       # 新しいカスタム値
            "receipt",       # 新しいカスタム値
            "tax_document",  # 新しいカスタム値（アンダースコア含む）
            "Form-2024",     # 新しいカスタム値（ハイフン含む）
        ]
        
        for session_type in session_types:
            test_args = [
                "-s", session_type,
                "-g", "./ground_truth",
                "-p", "./prediction"
            ]
            monkeypatch.setattr("sys.argv", ["main.py"] + test_args)
            
            args = main.parse_args()
            assert args.session_type == session_type

    @patch("src.main.Csv4dbEvaluator")
    def test_custom_session_type_in_execution(self, mock_evaluator, tmp_path, monkeypatch):
        """
        カスタムセッションタイプでmain関数が正常に実行されることを確認
        
        旧仕様: if section.lower() == "fal" or section.lower() == "bspl": で制限
        新仕様: if section is not None: で任意のセッションタイプを許可
        """
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"
        
        gt_dir.mkdir()
        pd_dir.mkdir()
        
        # ダミーCSVファイルを作成
        pandas.DataFrame({"col": ["val"]}).to_csv(gt_dir / "test.csv", index=False)
        pandas.DataFrame({"col": ["val"]}).to_csv(pd_dir / "test.csv", index=False)
        
        # モックの設定
        mock_evaluator_instance = MagicMock()
        mock_evaluator.return_value = mock_evaluator_instance
        
        # RESULTS_BASE_DIRを一時ディレクトリに設定
        monkeypatch.setattr("src.main.RESULTS_BASE_DIR", results_dir)
        
        # カスタムセッションタイプでコマンドライン引数を設定
        test_args = [
            "-s", "custom_invoice_type",
            "-g", str(gt_dir),
            "-p", str(pd_dir)
        ]
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)
        
        # main関数実行
        main.main()
        
        # Csv4dbEvaluatorが正しいsession名で呼び出されたことを確認
        mock_evaluator.assert_called_once()
        call_kwargs = mock_evaluator.call_args[1]
        assert call_kwargs['session'] == "custom_invoice_type"
        
        # compare_with_pandasが呼び出されたことを確認
        mock_evaluator_instance.compare_with_pandas.assert_called_once()

    @patch("src.main.Csv4dbEvaluator")
    def test_custom_session_type_with_config_file(self, mock_evaluator, tmp_path, monkeypatch):
        """
        設定ファイルでカスタムセッションタイプを使用できることを確認
        """
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"
        
        gt_dir.mkdir()
        pd_dir.mkdir()
        
        # ダミーCSVファイルを作成
        pandas.DataFrame({"col": ["val"]}).to_csv(gt_dir / "test.csv", index=False)
        pandas.DataFrame({"col": ["val"]}).to_csv(pd_dir / "test.csv", index=False)
        
        # カスタムセッションタイプを含む設定ファイル作成
        config_file = tmp_path / "test_config.toml"
        config_content = f"""
            [custom_document_type]
            prediction_dir = "{str(pd_dir).replace(chr(92), chr(92)*2)}"
            ground_truth_dir = "{str(gt_dir).replace(chr(92), chr(92)*2)}"
            
            [another_custom_type]
            prediction_dir = "{str(pd_dir).replace(chr(92), chr(92)*2)}"
            ground_truth_dir = "{str(gt_dir).replace(chr(92), chr(92)*2)}"
        """
        config_file.write_text(config_content, encoding="utf-8")
        
        # モックの設定
        mock_evaluator_instance = MagicMock()
        mock_evaluator.return_value = mock_evaluator_instance
        
        # RESULTS_BASE_DIRを一時ディレクトリに設定
        monkeypatch.setattr("src.main.RESULTS_BASE_DIR", results_dir)
        
        # コマンドライン引数の設定
        test_args = ["-c", str(config_file)]
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)
        
        # main関数実行
        main.main()
        
        # 両方のカスタムセッションタイプで呼び出されたことを確認
        assert mock_evaluator.call_count == 2
        
        # 呼び出されたセッション名を確認
        call_sessions = [call[1]['session'] for call in mock_evaluator.call_args_list]
        assert "custom_document_type" in call_sessions
        assert "another_custom_type" in call_sessions

    @patch("src.main.Csv4dbEvaluator")
    def test_session_type_used_as_folder_name(self, mock_evaluator, tmp_path, monkeypatch):
        """
        session_typeが結果ディレクトリのフォルダ名として使用されることを確認
        """
        gt_dir = tmp_path / "ground_truth"
        pd_dir = tmp_path / "prediction"
        results_dir = tmp_path / "results"
        
        gt_dir.mkdir()
        pd_dir.mkdir()
        
        # ダミーCSVファイルを作成
        pandas.DataFrame({"col": ["val"]}).to_csv(gt_dir / "test.csv", index=False)
        pandas.DataFrame({"col": ["val"]}).to_csv(pd_dir / "test.csv", index=False)
        
        # Evaluatorのモック設定（session_dirを実際に作成するように）
        def create_session_dir(*args, **kwargs):
            session = kwargs['session']
            results_base = kwargs['results_base_dir']
            session_dir = results_base / session
            session_dir.mkdir(parents=True, exist_ok=True)
            instance = MagicMock()
            instance.session_dir = session_dir
            return instance
        
        mock_evaluator.side_effect = create_session_dir
        
        # RESULTS_BASE_DIRを一時ディレクトリに設定
        monkeypatch.setattr("src.main.RESULTS_BASE_DIR", results_dir)
        
        custom_session_name = "my_custom_report_2024"
        
        # カスタムセッションタイプでコマンドライン引数を設定
        test_args = [
            "-s", custom_session_name,
            "-g", str(gt_dir),
            "-p", str(pd_dir)
        ]
        monkeypatch.setattr("sys.argv", ["main.py"] + test_args)
        
        # main関数実行
        main.main()
        
        # カスタムセッション名のディレクトリが作成されていることを確認
        expected_session_dir = results_dir / custom_session_name
        assert expected_session_dir.exists()
        assert expected_session_dir.is_dir()

