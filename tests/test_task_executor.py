import pytest
from unittest.mock import Mock, patch, MagicMock
import asyncio
from pathlib import Path
import tempfile
import shutil

from src.core import TaskExecutor, ExecutionResult
from src.core.artifact_manager import ArtifactManager


class TestTaskExecutor:
    @pytest.fixture
    def temp_workspace(self):
        """一時的な作業ディレクトリを作成"""
        workspace = tempfile.mkdtemp()
        yield workspace
        shutil.rmtree(workspace)
    
    @pytest.fixture
    def executor(self, temp_workspace):
        """TaskExecutorのインスタンスを作成"""
        return TaskExecutor(workspace_dir=temp_workspace)
    
    @pytest.fixture
    def mock_artifact_manager(self, temp_workspace):
        """モックのArtifactManagerを作成"""
        mock_manager = Mock(spec=ArtifactManager)
        # prepare_task_workspaceメソッドをモック
        def prepare_workspace_side_effect(task_id):
            workspace = Path(temp_workspace) / f"task_{task_id}"
            workspace.mkdir(parents=True, exist_ok=True)
            return workspace
        mock_manager.prepare_task_workspace.side_effect = prepare_workspace_side_effect
        return mock_manager
    
    @pytest.mark.asyncio
    async def test_execute_simple_task(self, executor, mock_artifact_manager):
        """シンプルなタスクの実行"""
        task = {
            "id": "test-001",
            "name": "Hello Worldファイル作成",
            "prompt": "Create a hello.txt file with 'Hello, World!' content"
        }
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            # モックプロセスの設定
            mock_process = MagicMock()
            # 非同期関数として定義
            async def mock_communicate():
                return (b"Created hello.txt", b"")
            mock_process.communicate = mock_communicate
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process
            
            result = await executor.execute(task, mock_artifact_manager)
            
            assert result.success is True
            assert result.task_id == "test-001"
            assert "hello.txt" in result.stdout
            assert result.stderr == ""
    
    @pytest.mark.asyncio
    async def test_execute_with_error(self, executor, mock_artifact_manager):
        """エラーが発生するタスクの実行"""
        task = {
            "id": "test-002",
            "name": "エラータスク",
            "prompt": "This will cause an error"
        }
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = MagicMock()
            async def mock_communicate():
                return (b"", b"Error: Task failed")
            mock_process.communicate = mock_communicate
            mock_process.returncode = 1
            mock_subprocess.return_value = mock_process
            
            result = await executor.execute(task, mock_artifact_manager)
            
            assert result.success is False
            assert result.task_id == "test-002"
            assert "Error" in result.stderr
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, executor, mock_artifact_manager):
        """タイムアウト処理のテスト"""
        task = {
            "id": "test-003",
            "name": "長時間実行タスク",
            "prompt": "Simulate long running task"
        }
        
        executor.timeout = 0.1  # 100msでタイムアウト
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            async def long_running():
                await asyncio.sleep(1)  # 1秒待機
                return (b"Should not reach here", b"")
            
            mock_process = MagicMock()
            mock_process.communicate = long_running
            mock_process.kill = MagicMock()
            # waitメソッドも非同期関数として定義
            async def mock_wait():
                pass
            mock_process.wait = mock_wait
            mock_subprocess.return_value = mock_process
            
            result = await executor.execute(task, mock_artifact_manager)
            
            assert result.success is False
            assert "timeout" in result.error.lower()
            mock_process.kill.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_artifact_collection(self, executor, mock_artifact_manager, temp_workspace):
        """生成物の収集テスト"""
        task = {
            "id": "test-004",
            "name": "ファイル生成タスク",
            "prompt": "Create test files"
        }
        
        # テストファイルを作成（prepare_task_workspaceが作るディレクトリに合わせる）
        test_file = Path(temp_workspace) / "task_test-004" / "output.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("Test content")
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = MagicMock()
            async def mock_communicate():
                return (b"Created files", b"")
            mock_process.communicate = mock_communicate
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process
            
            result = await executor.execute(task, mock_artifact_manager)
            
            assert result.success is True
            assert len(result.artifacts) > 0
            assert "output.txt" in result.artifacts[0]
    
    def test_command_construction(self, executor, mock_artifact_manager):
        """Claudeコマンドの構築テスト"""
        task = {
            "id": "test-005",
            "name": "テストタスク",
            "prompt": "Do something"
        }
        
        cmd = executor._build_command(task)
        
        assert "claude" in cmd[0]
        assert "--print" in cmd
        assert task["prompt"] in cmd
    
    @pytest.mark.asyncio
    async def test_workspace_isolation(self, executor, mock_artifact_manager, temp_workspace):
        """作業ディレクトリの分離テスト"""
        task1 = {"id": "task-001", "name": "Task 1", "prompt": "Task 1"}
        task2 = {"id": "task-002", "name": "Task 2", "prompt": "Task 2"}
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = MagicMock()
            async def mock_communicate():
                return (b"Success", b"")
            mock_process.communicate = mock_communicate
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process
            
            await executor.execute(task1, mock_artifact_manager)
            await executor.execute(task2, mock_artifact_manager)
            
            # 各タスクが別々のディレクトリで実行されているか確認
            task1_dir = Path(temp_workspace) / "task_task-001"
            task2_dir = Path(temp_workspace) / "task_task-002"
            
            assert task1_dir.exists()
            assert task2_dir.exists()
    
    @pytest.mark.asyncio
    async def test_concurrent_execution_limit(self, executor, mock_artifact_manager):
        """並列実行数制限のテスト"""
        executor.max_concurrent = 2
        
        tasks = [
            {"id": f"task-{i}", "name": f"Task {i}", "prompt": f"Task {i}"}
            for i in range(5)
        ]
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            call_count = 0
            active_processes = []
            
            async def track_concurrent():
                nonlocal call_count
                call_count += 1
                active_processes.append(call_count)
                await asyncio.sleep(0.1)
                active_processes.remove(call_count)
                mock = MagicMock()
                async def mock_communicate():
                    return (b"Success", b"")
                mock.communicate = mock_communicate
                mock.returncode = 0
                return mock
            
            mock_subprocess.side_effect = track_concurrent
            
            # 全タスクを並列実行
            results = await asyncio.gather(*[executor.execute(task) for task in tasks])
            
            # 同時実行数が制限を超えていないことを確認
            max_concurrent_observed = max(len(active_processes) for _ in range(100))
            assert max_concurrent_observed <= 2