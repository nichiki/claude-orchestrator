"""
共有コンテキスト機能のテスト
"""
import pytest
import asyncio
from pathlib import Path
import tempfile
import shutil
from unittest.mock import Mock, patch, AsyncMock

from src.core.artifact_manager import ArtifactManager, FileMetadata
from src.core.task_executor import TaskExecutor, ExecutionResult
from src.core.conflict_resolver import ConflictResolver, ConflictResolution


class TestSharedContext:
    """共有コンテキスト機能のテストスイート"""
    
    def setup_method(self):
        """各テストの前処理"""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_dir = Path(self.temp_dir) / "workspace"
        self.workspace_dir.mkdir()
        
    def teardown_method(self):
        """各テストの後処理"""
        shutil.rmtree(self.temp_dir)
        
    def test_prepare_task_workspace_empty(self):
        """共有ワークスペースが空の場合のテスト"""
        artifact_manager = ArtifactManager(workspace_dir=self.workspace_dir)
        
        # タスクワークスペースを準備
        task_workspace = artifact_manager.prepare_task_workspace("task1")
        
        assert task_workspace.exists()
        assert task_workspace.name == "task_task1"
        # .claudeディレクトリが作成されることを確認
        assert (task_workspace / ".claude").exists()
        assert (task_workspace / ".claude" / "settings.json").exists()
        # .claude以外は空であることを確認
        non_claude_files = [f for f in task_workspace.iterdir() if f.name != ".claude"]
        assert non_claude_files == []
        assert "task1" in artifact_manager.task_snapshots
        
    def test_prepare_task_workspace_with_shared_content(self):
        """共有ワークスペースにコンテンツがある場合のテスト"""
        artifact_manager = ArtifactManager(workspace_dir=self.workspace_dir)
        
        # 共有ワークスペースにファイルを作成
        shared_workspace = artifact_manager.shared_workspace
        shared_workspace.mkdir()
        (shared_workspace / "models.py").write_text("class User: pass")
        (shared_workspace / "utils").mkdir()
        (shared_workspace / "utils" / "helpers.py").write_text("def helper(): pass")
        
        # タスクワークスペースを準備
        task_workspace = artifact_manager.prepare_task_workspace("task2")
        
        # ファイルがコピーされていることを確認
        assert (task_workspace / "models.py").exists()
        assert (task_workspace / "models.py").read_text() == "class User: pass"
        assert (task_workspace / "utils" / "helpers.py").exists()
        assert (task_workspace / "utils" / "helpers.py").read_text() == "def helper(): pass"
        
    def test_snapshot_creation(self):
        """スナップショット作成のテスト"""
        artifact_manager = ArtifactManager(workspace_dir=self.workspace_dir)
        
        # テスト用ディレクトリを作成
        test_dir = self.workspace_dir / "test"
        test_dir.mkdir()
        (test_dir / "file1.py").write_text("content1")
        (test_dir / "file2.py").write_text("content2")
        (test_dir / "subdir").mkdir()
        (test_dir / "subdir" / "file3.py").write_text("content3")
        
        # スナップショットを作成
        snapshot = artifact_manager._create_snapshot(test_dir)
        
        assert len(snapshot) == 3
        assert "file1.py" in snapshot
        assert "file2.py" in snapshot
        assert "subdir/file3.py" in snapshot
        
        # メタデータを確認
        for file_path, metadata in snapshot.items():
            assert isinstance(metadata, FileMetadata)
            assert metadata.hash is not None
            assert metadata.size > 0
            assert metadata.mtime > 0
            
    def test_detect_changes(self):
        """差分検出のテスト"""
        artifact_manager = ArtifactManager(workspace_dir=self.workspace_dir)
        
        # ベーススナップショット
        base_snapshot = {
            "file1.py": FileMetadata(hash="hash1", size=100, mtime=1000),
            "file2.py": FileMetadata(hash="hash2", size=200, mtime=2000),
            "file3.py": FileMetadata(hash="hash3", size=300, mtime=3000),
        }
        
        # 現在のスナップショット（変更あり）
        current_snapshot = {
            "file1.py": FileMetadata(hash="hash1", size=100, mtime=1000),  # 変更なし
            "file2.py": FileMetadata(hash="hash2_modified", size=250, mtime=2500),  # 変更
            "file4.py": FileMetadata(hash="hash4", size=400, mtime=4000),  # 新規
            # file3.py は削除
        }
        
        changes = artifact_manager._detect_changes(base_snapshot, current_snapshot)
        
        assert set(changes["new"]) == {"file4.py"}
        assert set(changes["deleted"]) == {"file3.py"}
        assert set(changes["modified"]) == {"file2.py"}
        
    @pytest.mark.asyncio
    async def test_integrate_task_results_new_files(self):
        """新規ファイルの統合テスト"""
        artifact_manager = ArtifactManager(workspace_dir=self.workspace_dir)
        
        # タスクワークスペースを準備
        task_workspace = artifact_manager.prepare_task_workspace("task1")
        
        # タスクでファイルを作成
        (task_workspace / "new_file.py").write_text("new content")
        
        # 統合を実行
        result = await artifact_manager.integrate_task_results("task1", task_workspace)
        
        assert result["new"] == 1
        assert result["modified"] == 0
        assert result["conflict"] == 0
        
        # 共有ワークスペースに反映されていることを確認
        assert (artifact_manager.shared_workspace / "new_file.py").exists()
        assert (artifact_manager.shared_workspace / "new_file.py").read_text() == "new content"
        
    @pytest.mark.asyncio
    async def test_integrate_task_results_modified_files(self):
        """変更ファイルの統合テスト"""
        artifact_manager = ArtifactManager(workspace_dir=self.workspace_dir)
        
        # 共有ワークスペースにファイルを作成
        artifact_manager.shared_workspace.mkdir()
        (artifact_manager.shared_workspace / "existing.py").write_text("original content")
        
        # タスクワークスペースを準備
        task_workspace = artifact_manager.prepare_task_workspace("task1")
        
        # タスクでファイルを変更
        (task_workspace / "existing.py").write_text("modified content")
        
        # 統合を実行
        result = await artifact_manager.integrate_task_results("task1", task_workspace)
        
        assert result["new"] == 0
        assert result["modified"] == 1
        assert result["conflict"] == 0
        
        # 共有ワークスペースに反映されていることを確認
        assert (artifact_manager.shared_workspace / "existing.py").read_text() == "modified content"
        
    @pytest.mark.asyncio
    async def test_integrate_task_results_with_conflict(self):
        """競合がある場合の統合テスト"""
        artifact_manager = ArtifactManager(workspace_dir=self.workspace_dir)
        conflict_resolver = ConflictResolver(self.workspace_dir)
        
        # 共有ワークスペースにファイルを作成
        artifact_manager.shared_workspace.mkdir()
        (artifact_manager.shared_workspace / "conflict.py").write_text("original content")
        
        # タスク1のワークスペースを準備
        task1_workspace = artifact_manager.prepare_task_workspace("task1")
        (task1_workspace / "conflict.py").write_text("task1 content")
        
        # タスク1を統合
        await artifact_manager.integrate_task_results("task1", task1_workspace, conflict_resolver)
        
        # 共有ワークスペースが更新されていることを確認
        assert (artifact_manager.shared_workspace / "conflict.py").read_text() == "task1 content"
        
        # タスク2のワークスペースを準備（task1の変更前の状態から開始）
        task2_workspace = artifact_manager.prepare_task_workspace("task2")
        # スナップショットを手動で古い状態に設定（競合をシミュレート）
        artifact_manager.task_snapshots["task2"]["conflict.py"] = FileMetadata(
            hash="dummy_hash_for_old_version",  # ダミーハッシュ
            size=100,
            mtime=1000
        )
        (task2_workspace / "conflict.py").write_text("task2 content")
        
        # ConflictResolverをモック化
        with patch.object(conflict_resolver, 'resolve_three_way_conflict') as mock_resolve:
            mock_resolve.return_value = ConflictResolution(
                strategy="version",
                message="Cannot merge"
            )
            
            # タスク2を統合（競合発生）
            result = await artifact_manager.integrate_task_results("task2", task2_workspace, conflict_resolver)
            
            assert result["new"] == 0
            assert result["modified"] == 0
            assert result["conflict"] == 1
            
            # バージョンサフィックス付きファイルが作成されていることを確認
            assert (artifact_manager.shared_workspace / "conflict_task2.py").exists()
            
    @pytest.mark.asyncio
    async def test_task_executor_with_shared_context(self):
        """TaskExecutorの共有コンテキスト対応テスト"""
        artifact_manager = ArtifactManager(workspace_dir=self.workspace_dir)
        executor = TaskExecutor(workspace_dir=str(self.workspace_dir))
        
        # 共有ワークスペースにファイルを作成
        artifact_manager.shared_workspace.mkdir()
        (artifact_manager.shared_workspace / "shared_file.py").write_text("shared content")
        
        # モックタスクを実行
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"output", b"")
            mock_subprocess.return_value = mock_process
            
            task = {
                "id": "test_task",
                "name": "Test Task",
                "prompt": "test prompt",
                "shared_context": True
            }
            
            result = await executor.execute(task, artifact_manager)
            
            assert result.success
            assert result.workspace is not None
            assert result.workspace.name == "task_test_task"
            
            # 共有ファイルがコピーされていることを確認
            assert (result.workspace / "shared_file.py").exists()