"""
path_utils モジュールのユニットテスト
"""
import pytest
from pathlib import Path
from src.utils import pathutils


class TestGetProjectRootDir:
    """get_project_root_dir関数のテスト"""

    def test_returns_path_object(self):
        """Pathオブジェクトを返すことを確認"""
        result = pathutils.get_project_root_dir()
        assert isinstance(result, Path)

    def test_returns_existing_directory(self):
        """存在するディレクトリを返すことを確認"""
        result = pathutils.get_project_root_dir()
        assert result.exists()
        assert result.is_dir()

    def test_contains_git_or_pyproject(self):
        """返されるディレクトリに.gitまたはpyproject.tomlが含まれることを確認"""
        result = pathutils.get_project_root_dir()
        has_git = (result / ".git").exists()
        has_pyproject = (result / "pyproject.toml").exists()
        assert has_git or has_pyproject


class TestValidateDir:
    """validate_dir関数のテスト"""

    def test_valid_directory_does_not_raise(self, tmp_path):
        """有効なディレクトリでは例外が発生しないことを確認"""
        test_dir = tmp_path / "valid_dir"
        test_dir.mkdir()

        # 例外が発生しないことを確認
        pathutils.validate_dir(test_dir)

    def test_nonexistent_directory_raises_error(self, tmp_path):
        """存在しないディレクトリで例外が発生することを確認"""
        nonexistent_dir = tmp_path / "nonexistent"

        with pytest.raises(FileNotFoundError) as exc_info:
            pathutils.validate_dir(nonexistent_dir)

        assert "入力ディレクトリが存在しません" in str(exc_info.value)

    def test_file_path_raises_error(self, tmp_path):
        """ファイルパスを渡すと例外が発生することを確認"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        with pytest.raises(FileNotFoundError) as exc_info:
            pathutils.validate_dir(test_file)

        assert "入力されたパスがディレクトリではありません" in str(exc_info.value)


class TestValidateFile:
    """validate_file関数のテスト"""

    def test_valid_file_does_not_raise(self, tmp_path):
        """有効なファイルでは例外が発生しないことを確認"""
        test_file = tmp_path / "valid_file.txt"
        test_file.write_text("test content")

        # 例外が発生しないことを確認
        pathutils.validate_file(test_file)

    def test_nonexistent_file_raises_error(self, tmp_path):
        """存在しないファイルで例外が発生することを確認"""
        nonexistent_file = tmp_path / "nonexistent.txt"

        with pytest.raises(FileNotFoundError) as exc_info:
            pathutils.validate_file(nonexistent_file)

        assert "入力ファイルが存在しません" in str(exc_info.value)

    def test_directory_path_raises_error(self, tmp_path):
        """ディレクトリパスを渡すと例外が発生することを確認"""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        with pytest.raises(FileNotFoundError) as exc_info:
            pathutils.validate_file(test_dir)

        assert "入力されたパスがファイルではありません" in str(exc_info.value)


class TestSetupDir:
    """setup_dir関数のテスト"""

    def test_creates_new_directory(self, tmp_path):
        """新しいディレクトリが作成されることを確認"""
        new_dir = tmp_path / "new_directory"
        assert not new_dir.exists()

        pathutils.setup_dir(new_dir)

        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_creates_nested_directories(self, tmp_path):
        """ネストしたディレクトリが作成されることを確認"""
        nested_dir = tmp_path / "level1" / "level2" / "level3"
        assert not nested_dir.exists()

        pathutils.setup_dir(nested_dir)

        assert nested_dir.exists()
        assert nested_dir.is_dir()

    def test_existing_directory_does_not_raise(self, tmp_path):
        """既存のディレクトリでも例外が発生しないことを確認"""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()

        # 例外が発生しないことを確認
        pathutils.setup_dir(existing_dir)

        assert existing_dir.exists()
