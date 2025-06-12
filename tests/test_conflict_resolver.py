"""
ConflictResolverのテスト
"""
import pytest
import asyncio
from pathlib import Path
import tempfile
import shutil
from unittest.mock import Mock, patch, AsyncMock

from src.core.conflict_resolver import ConflictResolver, ConflictResolution
from src.core.task_executor import ExecutionResult


class TestConflictResolver:
    """ConflictResolverのテストスイート"""
    
    def setup_method(self):
        """各テストの前処理"""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_dir = Path(self.temp_dir)
        self.resolver = ConflictResolver(self.workspace_dir)
        
    def teardown_method(self):
        """各テストの後処理"""
        shutil.rmtree(self.temp_dir)
        
    @pytest.mark.asyncio
    async def test_resolve_conflict_successful_merge(self):
        """2-wayマージが成功する場合のテスト"""
        # テストファイルを作成
        existing_file = self.workspace_dir / "test.py"
        existing_file.write_text("def foo():\n    return 1")
        
        new_file = self.workspace_dir / "test_new.py"
        new_file.write_text("def foo():\n    return 2")
        
        # TaskExecutorをモック化
        with patch.object(self.resolver.executor, 'execute') as mock_execute:
            # マージタスクの実行をシミュレート
            async def execute_merge(task_dict):
                task_id = task_dict["id"]
                merge_task_dir = self.resolver.merge_workspace / task_id
                merge_task_dir.mkdir(parents=True)
                merged_file = merge_task_dir / "test.py"
                merged_file.write_text("# Merged version\ndef foo():\n    return 1  # from existing\n    return 2  # from new")
                
                return ExecutionResult(
                    task_id=task_id,
                    success=True,
                    stdout="Merge completed",
                    artifacts=["test.py"]
                )
            
            mock_execute.side_effect = execute_merge
            
            # マージを実行
            result = await self.resolver.resolve_conflict(existing_file, new_file, "task1")
            
            assert result.strategy == "merged"
            assert result.merged_file_path is not None
            assert result.merged_file_path.name == "test.py"
            assert "Successfully merged" in result.message
            
    @pytest.mark.asyncio
    async def test_resolve_conflict_cannot_merge(self):
        """マージ不可能な場合のテスト"""
        # テストファイルを作成
        existing_file = self.workspace_dir / "test.py"
        existing_file.write_text("completely different content")
        
        new_file = self.workspace_dir / "test_new.py"
        new_file.write_text("totally unrelated content")
        
        # TaskExecutorをモック化
        with patch.object(self.resolver.executor, 'execute') as mock_execute:
            # マージタスクの実行をシミュレート
            async def execute_cannot_merge(task_dict):
                task_id = task_dict["id"]
                merge_task_dir = self.resolver.merge_workspace / task_id
                merge_task_dir.mkdir(parents=True)
                cannot_merge_file = merge_task_dir / "CANNOT_MERGE.txt"
                cannot_merge_file.write_text("Files are fundamentally incompatible")
                
                return ExecutionResult(
                    task_id=task_id,
                    success=True,
                    stdout="Cannot merge",
                    artifacts=["CANNOT_MERGE.txt"]
                )
            
            mock_execute.side_effect = execute_cannot_merge
            
            # マージを実行
            result = await self.resolver.resolve_conflict(existing_file, new_file, "task1")
            
            assert result.strategy == "version"
            assert result.merged_file_path is None
            assert "Cannot merge" in result.message
            
    @pytest.mark.asyncio
    async def test_resolve_conflict_task_failure(self):
        """マージタスクが失敗する場合のテスト"""
        # テストファイルを作成
        existing_file = self.workspace_dir / "test.py"
        existing_file.write_text("content")
        
        new_file = self.workspace_dir / "test_new.py"
        new_file.write_text("new content")
        
        # TaskExecutorをモック化
        with patch.object(self.resolver.executor, 'execute') as mock_execute:
            mock_execute.return_value = ExecutionResult(
                task_id="merge_test_1234567890",
                success=False,
                error="Claude execution failed"
            )
            
            # マージを実行
            result = await self.resolver.resolve_conflict(existing_file, new_file, "task1")
            
            assert result.strategy == "version"
            assert result.merged_file_path is None
            assert "Merge task failed" in result.message
            
    @pytest.mark.asyncio
    async def test_resolve_three_way_conflict_successful(self):
        """3-wayマージが成功する場合のテスト"""
        # テストファイルを作成
        base_file = self.workspace_dir / "base.py"
        base_file.write_text("def foo():\n    return 0")
        
        shared_file = self.workspace_dir / "shared.py"
        shared_file.write_text("def foo():\n    return 1  # shared change")
        
        task_file = self.workspace_dir / "task.py"
        task_file.write_text("def foo():\n    return 0\n    # task addition")
        
        # TaskExecutorをモック化
        with patch.object(self.resolver.executor, 'execute') as mock_execute:
            # マージタスクの実行をシミュレート
            async def execute_3way_merge(task_dict):
                task_id = task_dict["id"]
                merge_task_dir = self.resolver.merge_workspace / task_id
                merge_task_dir.mkdir(parents=True)
                merged_file = merge_task_dir / "shared.py"
                merged_file.write_text("def foo():\n    return 1  # shared change\n    # task addition")
                
                return ExecutionResult(
                    task_id=task_id,
                    success=True,
                    stdout="3-way merge completed",
                    artifacts=["shared.py"]
                )
            
            mock_execute.side_effect = execute_3way_merge
            
            # 3-wayマージを実行
            result = await self.resolver.resolve_three_way_conflict(
                base_file, shared_file, task_file, "task1"
            )
            
            assert result.strategy == "merged"
            assert result.merged_file_path is not None
            assert result.merged_file_path.name == "shared.py"
            assert "Successfully merged" in result.message
            
    @pytest.mark.asyncio
    async def test_resolve_three_way_conflict_no_base(self):
        """ベースファイルがない場合の3-wayマージテスト"""
        # テストファイルを作成（ベースなし）
        shared_file = self.workspace_dir / "shared.py"
        shared_file.write_text("shared content")
        
        task_file = self.workspace_dir / "task.py"
        task_file.write_text("task content")
        
        # TaskExecutorをモック化
        with patch.object(self.resolver.executor, 'execute') as mock_execute:
            # execute呼び出し時の引数を検証
            async def check_prompt(task_dict):
                prompt = task_dict["prompt"]
                assert "# File did not exist in base version" in prompt
                
                merge_task_dir = self.resolver.merge_workspace / task_dict["id"]
                merge_task_dir.mkdir(parents=True)
                merged_file = merge_task_dir / "shared.py"
                merged_file.write_text("merged without base")
                
                return ExecutionResult(
                    task_id=task_dict["id"],
                    success=True,
                    stdout="Merged",
                    artifacts=["shared.py"]
                )
            
            mock_execute.side_effect = check_prompt
            
            # 3-wayマージを実行（ベースファイルなし）
            result = await self.resolver.resolve_three_way_conflict(
                None, shared_file, task_file, "task1"
            )
            
            assert result.strategy == "merged"
            assert result.merged_file_path is not None
            
    def test_create_merge_prompt(self):
        """マージプロンプト生成のテスト"""
        # テストファイルを作成
        existing_file = self.workspace_dir / "test.py"
        existing_file.write_text("existing content")
        
        new_file = self.workspace_dir / "new" / "test.py"
        new_file.parent.mkdir()
        new_file.write_text("new content")
        
        # プロンプトを生成
        prompt = self.resolver._create_merge_prompt(existing_file, new_file)
        
        assert "test.py" in prompt
        assert "existing content" in prompt
        assert "new content" in prompt
        assert "from new" in prompt
        assert "intelligent merge" in prompt
        
    def test_create_three_way_merge_prompt(self):
        """3-wayマージプロンプト生成のテスト"""
        # テストファイルを作成
        base_file = self.workspace_dir / "base.py"
        base_file.write_text("base content")
        
        shared_file = self.workspace_dir / "shared.py"
        shared_file.write_text("shared content")
        
        task_file = self.workspace_dir / "task.py"
        task_file.write_text("task content")
        
        # プロンプトを生成
        prompt = self.resolver._create_three_way_merge_prompt(base_file, shared_file, task_file)
        
        assert "3-way merge" in prompt
        assert "BASE version" in prompt
        assert "SHARED version" in prompt
        assert "TASK version" in prompt
        assert "base content" in prompt
        assert "shared content" in prompt
        assert "task content" in prompt
        
    def test_cleanup_merge_workspace(self):
        """マージワークスペースのクリーンアップテスト"""
        # マージワークスペースにファイルを作成
        test_file = self.resolver.merge_workspace / "test.txt"
        test_file.write_text("test")
        
        assert self.resolver.merge_workspace.exists()
        
        # クリーンアップ
        self.resolver.cleanup_merge_workspace()
        
        assert not self.resolver.merge_workspace.exists()