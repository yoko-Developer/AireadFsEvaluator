# AireadFsEvaluator

AIReadで読み取った財務諸表（Financial Statements）のOCR結果を、
人間が作成した正解データ（Ground Truth）と比較して評価するためのツールです。

AIReadの出力結果をそのまま評価対象とし、
帳票・項目ごとの一致／不一致や、欠損・過剰などを確認できます。

## 概要

本プロジェクトでは、決算書などの帳票をAIReadでOCR処理し、
その結果と正解データを比較することでOCR精度を評価します。

主な対象は以下です。

- 貸借対照表
- 損益計算書
- 製造原価報告書
- 販売費及び一般管理費明細書
- 株主資本等変動計算書
- キャッシュ・フロー計算書
- 個別注記表
- その他の対象帳票

評価に使用するGround Truthは、PDFを確認して作成したマスタデータです。

## 主な機能

- AIRead出力とGround TruthのCSV比較
- 項目・行・列の比較
- 一致／不一致の判定
- 欠損・過剰データの確認
- 評価結果の集計
- 詳細な比較結果の出力

## ディレクトリ構成

```text
AireadFsEvaluator/
│
├── src/                       # アプリケーション本体
│   ├── main.py
│   ├── constants.py
│   ├── eval/                  # 評価処理
│   ├── gui/                   # GUI
│   └── utils/                 # 共通処理
│
├── tests/                     # テストコード
│
├── data/
│   ├── ground_truth/
│   │   └── fs/                # Ground Truth
│   │
│   └── row/
│       ├── fs/                # AIRead実行・予測データ
│       │   ├── input/         # 入力PDF
│       │   ├── output/        # AIRead出力
│       │   ├── debug/         # デバッグ出力
│       │   ├── failed/        # 処理失敗データ
│       │   ├── logs/          # ログ
│       │   ├── success/       # 処理成功データ
│       │   └── AIRead_conf/   # AIRead設定
│       │
│       └── _tessdata/
│           └── tessdata/      # OCRモデル・辞書等
│
├── results/
│   └── fs/                    # 評価結果
│
├── .azure-pipelines/          # CI/CD設定
├── pytest.ini                 # pytest設定
├── requirements.txt           # 実行用依存パッケージ
├── requirements-test.txt      # テスト用依存パッケージ
└── README.md
```

## Ground Truth と Prediction
評価では、以下の2種類のデータを比較します。

**Ground Truth**

PDFを確認して作成した正解データです。

```
data/ground_truth/fs/
```

**Prediction**

AIReadを実行して取得したOCR結果です。

```
data/row/fs/
```

比較するため、Ground TruthとPredictionのファイル名を一致させます。

## AIRead設定
AIReadの実行に必要な設定は、以下に配置します。

```
data/row/fs/AIRead_conf/
```
OCRモデル・辞書などは以下を使用します。
```
data/row/_tessdata/tessdata/
```

AIReadのバージョンアップ時には、
AIRead本体だけでなく、設定ファイルやOCR関連ファイルについても
必要な差分を確認します。

## 評価対象の帳票
現在の分類設定には、以下の帳票を含みます。


| form_id | 帳票 |
|---|---|
| 01_010_02_01 | 貸借対照表 |
| 01_020_02_01 | 損益計算書 |
| 01_030_02_01 | 製造原価報告書 |
| 01_040_02_01 | 販売費及び一般管理費 |
| 01_050_02_01 | 株主資本等変動計算書 |
| 01_060_02_01 | キャッシュ・フロー計算書 |
| 01_070_02_01 | 個別注記表 |
| 02_050_02_01 | 棚卸資産 内訳書 |

## 使用方法

1. **データを配置**
   - AIReadの出力結果：`data/row/fs/`
   - Ground Truth：`data/ground_truth/fs/`
   - 比較するファイル名を一致させる
2. 評価を実行
  ```bash
   python -m src.main -c config.toml -s fs
   ```

3. 結果を確認
   - 評価結果：results/fs/

## テスト
ユニットテストを実行します。
```
pytest tests -v
```

カバレッジを取得する場合：
```
pytest tests --cov=src --cov-report=html
```

## 開発
機能追加・修正はブランチを分けて行い、動作確認・テスト後にマージします。
