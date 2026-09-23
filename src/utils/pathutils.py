# standard library
from pathlib import Path


def get_project_root_dir() -> Path:
    # 現在地から上に遡って .git があるディレクトリを探す
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    # 見つからない場合は現在のファイルの親を返す
    return Path(__file__).resolve().parent

def validate_dir(target_dir: Path) -> None:
    if not target_dir.exists():
        raise FileNotFoundError(f"入力ディレクトリが存在しません: {target_dir}")
    if not target_dir.is_dir():
        raise FileNotFoundError(f"入力されたパスがディレクトリではありません: {target_dir}")

def validate_file(target_file: Path) -> None:
    if not target_file.exists():
        raise FileNotFoundError(f"入力ファイルが存在しません: {target_file}")
    if not target_file.is_file():
        raise FileNotFoundError(f"入力されたパスがファイルではありません: {target_file}")

def setup_dir(target_dir: Path) -> None:
    if not target_dir.exists():
        target_dir.mkdir(parents=True)