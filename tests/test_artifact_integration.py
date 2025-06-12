import pytest
import tempfile
from pathlib import Path
from src.core.artifact_manager import ArtifactManager


class TestArtifactIntegration:
    
    @pytest.mark.asyncio
    async def test_integrate_artifact_no_conflict(self):
        """競合なしの場合の統合テスト"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            manager = ArtifactManager()
            
            # ソースファイルを作成
            source_file = workspace / "task1" / "models.py"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("# Models content")
            
            # 統合先ディレクトリ
            dest_dir = workspace / "integrated"
            
            # 統合実行
            actual_path = await manager.integrate_artifact(source_file, dest_dir, "task1")
            
            # 検証
            assert actual_path.exists()
            assert actual_path.name == "models.py"
            assert actual_path.read_text() == "# Models content"
    
    @pytest.mark.asyncio
    async def test_integrate_artifact_with_conflict(self):
        """競合ありの場合のバージョニングテスト"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            manager = ArtifactManager()
            
            # 統合先ディレクトリ
            dest_dir = workspace / "integrated"
            dest_dir.mkdir(parents=True)
            
            # 既存ファイルを作成
            existing_file = dest_dir / "models.py"
            existing_file.write_text("# Original models")
            
            # 新しいファイルを統合
            source_file = workspace / "task2" / "models.py"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("# New models from task2")
            
            # 統合実行
            actual_path = await manager.integrate_artifact(source_file, dest_dir, "task2")
            
            # 検証
            assert actual_path.exists()
            assert actual_path.name == "models_task2.py"  # バージョニングされた名前
            assert actual_path.read_text() == "# New models from task2"
            
            # 元のファイルは変更されていない
            assert existing_file.read_text() == "# Original models"
    
    @pytest.mark.asyncio
    async def test_integrate_multiple_conflicts(self):
        """複数の競合がある場合のテスト"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            manager = ArtifactManager()
            
            dest_dir = workspace / "integrated"
            dest_dir.mkdir(parents=True)
            
            # 既存ファイル
            (dest_dir / "main.py").write_text("# Original main")
            
            # task1からmain.pyを統合
            source1 = workspace / "task1" / "main.py"
            source1.parent.mkdir(parents=True)
            source1.write_text("# Main from task1")
            
            path1 = await manager.integrate_artifact(source1, dest_dir, "task1")
            assert path1.name == "main_task1.py"
            
            # task2からもmain.pyを統合
            source2 = workspace / "task2" / "main.py"
            source2.parent.mkdir(parents=True)
            source2.write_text("# Main from task2")
            
            path2 = await manager.integrate_artifact(source2, dest_dir, "task2")
            assert path2.name == "main_task2.py"
            
            # 全てのファイルが存在することを確認
            assert (dest_dir / "main.py").exists()
            assert (dest_dir / "main_task1.py").exists()
            assert (dest_dir / "main_task2.py").exists()