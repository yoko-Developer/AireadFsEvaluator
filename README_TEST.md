# AIReadAccuracyEvaluationTest - テストガイド

## 概要

このドキュメントでは、AIReadAccuracyEvaluationTestプロジェクトのテスト実装と実行方法について説明します。

## テスト構造

```
tests/
├── __init__.py                # testsパッケージ初期化
├── conftest.py               # pytestフィクスチャとグローバル設定
├── test_path_utils.py        # path_utilsモジュールのテスト
├── test_fal_evaluator.py     # FalEvaluatorクラスのテスト
└── test_main.py              # mainモジュールのテスト
```

## テスト環境のセットアップ

### 1. 仮想環境の準備

```cmd
# 仮想環境がない場合は作成
python -m venv .venv

# 仮想環境を有効化（Windows）
.venv\Scripts\activate

# 仮想環境を有効化（Linux/Mac）
source .venv/bin/activate
```

### 2. テスト依存パッケージのインストール

```cmd
# 本体の依存パッケージをインストール
pip install -r requirements.txt

# テスト用の依存パッケージをインストール
pip install -r requirements-test.txt
```

## テストの実行

### 基本的な実行

```cmd
# 全テストを実行
pytest

# 特定のテストファイルを実行
pytest tests/test_path_utils.py

# 特定のテストクラスを実行
pytest tests/test_fal_evaluator.py::TestFalEvaluatorInit

# 特定のテストケースを実行
pytest tests/test_fal_evaluator.py::TestFalEvaluatorInit::test_initialization_creates_session_dir
```

### 詳細な出力で実行

```cmd
# より詳細な出力
pytest -v

# さらに詳細な出力（各テストの詳細を表示）
pytest -vv

# 失敗したテストのみ表示
pytest --tb=short
```

### カバレッジレポートの生成

```cmd
# カバレッジを計測しながらテスト実行
pytest --cov=src --cov-report=html

# カバレッジレポートをブラウザで確認
# htmlcov/index.html を開く
```

### マーカーを使った実行

```cmd
# ユニットテストのみ実行
pytest -m unit

# 統合テストのみ実行
pytest -m integration

# 特定のマーカー以外を実行
pytest -m "not slow"
```

## テストの種類

### 1. ユニットテスト

個々の関数やメソッドが正しく動作することを確認するテストです。

- `test_path_utils.py`: パスユーティリティ関数のテスト
  - ディレクトリ/ファイルの検証
  - プロジェクトルートの取得
  - ディレクトリのセットアップ

### 2. クラステスト

FalEvaluatorクラスの各メソッドが正しく動作することを確認するテストです。

- `test_fal_evaluator.py`: FalEvaluatorのテスト
  - 初期化処理
  - テキスト正規化
  - 類似度計算
  - 精度計算
  - CSVファイルの読み込み
  - 差分抽出

### 3. 統合テスト

複数のコンポーネントが連携して動作することを確認するテストです。

- `test_main.py`: mainモジュールの統合テスト
  - コマンドライン引数の解析
  - 設定ファイルの読み込み
  - エンドツーエンドの実行フロー

## テストデータ

テストでは`conftest.py`で定義されたフィクスチャを使用して、一時的なテストデータを作成します。

主なフィクスチャ：
- `temp_test_dir`: 一時的なテストディレクトリ
- `sample_gt_csv`: サンプルの正解データCSV
- `sample_pd_csv_perfect_match`: 完全一致する予測データCSV
- `sample_pd_csv_with_errors`: エラーを含む予測データCSV
- `sample_pd_csv_with_extra_column`: 過剰列を含む予測データCSV
- `sample_pd_csv_with_extra_row`: 過剰行を含む予測データCSV
- `sample_config_toml`: サンプル設定ファイル

## トラブルシューティング

### よくある問題

#### 1. モジュールが見つからない

```
ModuleNotFoundError: No module named 'src'
```

**解決策**: プロジェクトルートディレクトリで実行してください。

```cmd
cd C:\work\repository\AIReadAccuracyEvaluationTest
pytest
```

#### 2. 仮想環境が有効化されていない

```
'pytest' is not recognized as an internal or external command
```

**解決策**: 仮想環境を有効化してください。

```cmd
.venv\Scripts\activate
```

#### 3. テストが失敗する

特定のテストが失敗する場合は、詳細な出力を確認してください。

```cmd
pytest -vv --tb=long
```

## CI/CD統合

### Azure Pipelines

プロジェクトにAzure Pipelinesを統合する場合のサンプル設定：

```yaml
# azure-pipelines.yml に追加
- script: |
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    pip install -r requirements-test.txt
  displayName: 'Install dependencies'

- script: |
    pytest --junitxml=test-results.xml --cov=src --cov-report=xml
  displayName: 'Run tests'

- task: PublishTestResults@2
  inputs:
    testResultsFiles: 'test-results.xml'
    testRunTitle: 'Python Tests'

- task: PublishCodeCoverageResults@1
  inputs:
    codeCoverageTool: 'Cobertura'
    summaryFileLocation: 'coverage.xml'
```

## ベストプラクティス

1. **テストの独立性**: 各テストは他のテストに依存せず、独立して実行できるようにする
2. **明確なテスト名**: テストの意図が明確に分かる名前を付ける
3. **一時ディレクトリの使用**: `tmp_path`フィクスチャを使用してテスト用の一時ファイルを作成
4. **モックの活用**: 外部依存を持つコードはモックを使用してテスト
5. **適切なアサーション**: 期待される結果を明確にアサーション

## 参考資料

- [pytest公式ドキュメント](https://docs.pytest.org/)
- [pytest-cov](https://pytest-cov.readthedocs.io/)
- [Python Testing Best Practices](https://docs.python-guide.org/writing/tests/)
