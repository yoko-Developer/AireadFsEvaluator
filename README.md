# AireadFsEvaluator

AIReadで読み取った決算書（Financial Statements）のOCR精度を自動で評価するためのテストツールです。
人間が作成した正解データ（Ground Truth）と、AIReadの出力結果（Prediction）を比較し、詳細な精度レポートを生成します。

## 概要

このプロジェクトは、決算書（BS/PL等）読取機能の精度を自動的に評価するための独立したツールです。CSVファイルの比較により、項目精度、欠損・過剰の検出、差分レポートの生成を行います。

## 主な機能

- **CSV比較エンジン**: 正解データとAIRead出力結果の比較
- **CSV行列のファジーマッチング**: 列・行の近似マッチングによる柔軟な比較
- **詳細レポート**: HTML/CSV形式での視覚的な差分レポート
- **サマリー統計**: 精度指標の集計とレポート生成

## ディレクトリ構成

```
AireadFsEvaluator/
├── src/                          # ソースコード
│   ├── main.py                   # メインエントリーポイント
│   ├── constants.py              # 定数定義
│   ├── eval/                     # 評価モジュール
│   │   └── csv4db_evaluator.py   # CSV比較のコアロジック
│   ├── gui/                      # GUIモジュール
│   │   ├── gui.py                # アプリ画面＆ブラウザ自動起動
│   │   └── pink_theme.json       # カラーテーマ設定
│   └── utils/                    # ユーティリティ（cmd_executer, fileutils 等）
│
├── tests/                        # テストコード類
│   ├── conftest.py
│   └── test_*.py                 # 各種ユニットテスト
│
├── data/                         # データディレクトリ
│   ├── ground_truth/             # 正解マスタデータ置き場
│   │   └── fs/                   # マスタCSV
│   └── row/                      # AIRead処理エリア
│       └── fs/                   # 解析対象のPDF
│
├── results/                      # 実行時に自動作成される評価結果出力先
│   └── fs/                       # 実行結果（summary_report.csv や個別HTML等）
│
├── pytest.ini
├── requirements-test.txt
└── README.md
```

## Getting Started

### 前提条件

- Python 3.10以上
- 仮想環境 (推奨)

### インストール

1. リポジトリをクローン
```bash
git clone git@github.com:yoko-Developer/AireadFsEvaluator.git
cd AireadFsEvaluator
```

2. 依存パッケージのインストール

```PowerShell
pip install -r requirements.txt
pip install -r requirements-test.txt
```

3. 設定ファイル
   
config.toml に決算書（fs）専用のターゲットディレクトリを定義します。

```PowerShell
[fs]
prediction_dir = "./data/row/fs"
ground_truth_dir = "./data/ground_truth/fs"
```

## 使用方法
1. データの配置
- AIReadの出力結果 (CSV) を ./data/row/fs/ に配置します。
- 人間が作成した正解データ (CSV) を ./data/ground_truth/fs/ に配置します。

    ※比較を行うため、双方のファイル名は完全に一致させてください。

2. 評価の実行
   
   設定ファイルを指定し、セッションタイプを fs に指定して実行します。

   ```PowerShell
   python -m src.main -c config.toml -s fs
   ```

3. 出力結果

実行後、results/fs/ ディレクトリに以下のレポートが自動生成されます。

```
results/
└── fs/
    ├── summary_report.csv                    # 決算書全体のサマリーレポート
    └── individual reports/                   # 個別ファイルのレポート
        ├── html/                             # HTML形式の視覚的差分レポート
        │   └── diff_*.html
        └── csv/                              # CSV形式の詳細レポート
            └── */
                ├── diff_list_*.csv           # 項目ごとの差分リスト
                └── full_comparison_*.csv     # 全データ比較
```

## Build and Test

### UT(ユニットテスト) の実行

```PowerShell
# 全テストを一括実行
pytest tests -v

# カバレッジレポートの生成
pytest tests --cov=src --cov-report=html
```

## 開発規約
- コードスタイル: PEP 8準拠、SpringBootライクな厳格なクラス設計と型ヒントの徹底。

- ブランチ戦略: 機能追加は feature/ ブランチで行い、自動テスト（CI/CD）の通過を確認後に main へマージ。
