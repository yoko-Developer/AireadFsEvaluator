# 決算5票 精度評価テスト (Financial Statements)

これは、決算5票のPDFをAIReadで読み取った結果が、どれくらい合っているかをパースするための実験室です。

## フォルダレイアウト
```
data_fs/               👈 dataフォルダをコピーして名前を変えたもの
├── ground_truth/
│   └── fs/            👈 元々あった「fal」フォルダの名前を「fs」に変える！
└── row/
```


- `data_fs/ground_truth/fs/` : 人間が作った「100%正しい正解CSV」を入れる場所です。
- `data_fs/row/` : 実験に使う生データを置いておく場所です。

## 実行方法

### 1. 準備
```cmd
.venv\Scripts\activate
```

### 2. 実行
```python
python -m src.main -s fs -g ./data_fs/ground_truth/bspl -p ./data_fs/row/bspl/output
```

### 3. 出力結果
results/fs/
