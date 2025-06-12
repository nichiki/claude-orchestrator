import pytest
import asyncio
from pathlib import Path
import tempfile
import yaml

from src.core import Orchestrator, TaskStatus


class TestOrchestrator:
    @pytest.fixture
    def simple_wbs_file(self):
        """シンプルなWBSファイルを作成"""
        wbs_data = {
            "project": {
                "name": "テストプロジェクト"
            },
            "phases": [
                {
                    "id": "phase1",
                    "tasks": [
                        {
                            "id": "task-001",
                            "name": "Hello Worldファイル作成",
                            "prompt": "Create a file named hello.txt with content 'Hello, World!'",
                            "dependencies": []
                        },
                        {
                            "id": "task-002",
                            "name": "Goodbyeファイル作成",
                            "prompt": "Create a file named goodbye.txt with content 'Goodbye!'",
                            "dependencies": ["task-001"]
                        }
                    ]
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(wbs_data, f)
            return f.name
    
    @pytest.fixture
    def parallel_wbs_file(self):
        """並列実行可能なタスクを含むWBS"""
        wbs_data = {
            "project": {
                "name": "並列実行テスト"
            },
            "phases": [
                {
                    "id": "phase1",
                    "tasks": [
                        {
                            "id": "task-001",
                            "name": "ファイルA作成",
                            "prompt": "Create fileA.txt",
                            "dependencies": []
                        },
                        {
                            "id": "task-002",
                            "name": "ファイルB作成",
                            "prompt": "Create fileB.txt",
                            "dependencies": []
                        },
                        {
                            "id": "task-003",
                            "name": "マージファイル作成",
                            "prompt": "Create merged.txt",
                            "dependencies": ["task-001", "task-002"]
                        }
                    ]
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(wbs_data, f)
            return f.name
    
    @pytest.mark.asyncio
    async def test_simple_sequential_execution(self, simple_wbs_file, tmp_path):
        """シンプルな順次実行のテスト"""
        orchestrator = Orchestrator(
            wbs_path=simple_wbs_file,
            workspace_dir=str(tmp_path),
            dry_run=True  # 実際のClaude実行はスキップ
        )
        
        results = await orchestrator.run()
        
        # 両方のタスクが完了していることを確認
        assert len(results) == 2
        assert all(r.success for r in results)
        
        # 実行順序の確認（task-001が先）
        assert results[0].task_id == "task-001"
        assert results[1].task_id == "task-002"
    
    @pytest.mark.asyncio
    async def test_parallel_execution(self, parallel_wbs_file, tmp_path):
        """並列実行のテスト"""
        orchestrator = Orchestrator(
            wbs_path=parallel_wbs_file,
            workspace_dir=str(tmp_path),
            dry_run=True,
            max_concurrent=2
        )
        
        results = await orchestrator.run()
        
        assert len(results) == 3
        assert all(r.success for r in results)
        
        # task-001とtask-002は並列実行されるので、順序は保証されない
        first_two_ids = {results[0].task_id, results[1].task_id}
        assert first_two_ids == {"task-001", "task-002"}
        
        # task-003は最後に実行される
        assert results[2].task_id == "task-003"
    
    @pytest.mark.asyncio
    async def test_error_handling(self, tmp_path):
        """エラーハンドリングのテスト"""
        wbs_data = {
            "project": {"name": "エラーテスト"},
            "phases": [{
                "id": "phase1",
                "tasks": [
                    {
                        "id": "task-001",
                        "name": "失敗するタスク",
                        "prompt": "This will fail",
                        "dependencies": []
                    },
                    {
                        "id": "task-002",
                        "name": "依存タスク",
                        "prompt": "This depends on failed task",
                        "dependencies": ["task-001"]
                    }
                ]
            }]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(wbs_data, f)
            wbs_path = f.name
        
        orchestrator = Orchestrator(
            wbs_path=wbs_path,
            workspace_dir=str(tmp_path),
            dry_run=True,
            fail_fast=True  # 最初のエラーで停止
        )
        
        # エラーをシミュレート
        orchestrator._simulate_error = "task-001"
        
        with pytest.raises(RuntimeError, match="Task task-001 failed"):
            await orchestrator.run()
    
    def test_progress_callback(self, simple_wbs_file, tmp_path):
        """進捗コールバックのテスト"""
        progress_updates = []
        
        def on_progress(update):
            progress_updates.append(update)
        
        orchestrator = Orchestrator(
            wbs_path=simple_wbs_file,
            workspace_dir=str(tmp_path),
            dry_run=True,
            progress_callback=on_progress
        )
        
        asyncio.run(orchestrator.run())
        
        # 進捗更新が記録されているか確認
        assert len(progress_updates) > 0
        assert any(u["type"] == "task_started" for u in progress_updates)
        assert any(u["type"] == "task_completed" for u in progress_updates)
    
    @pytest.mark.asyncio
    async def test_state_persistence(self, simple_wbs_file, tmp_path):
        """状態の永続化テスト"""
        state_file = tmp_path / "state.json"
        
        orchestrator = Orchestrator(
            wbs_path=simple_wbs_file,
            workspace_dir=str(tmp_path),
            state_file=str(state_file),
            dry_run=True
        )
        
        # 最初のタスクだけ実行
        orchestrator._max_tasks = 1
        await orchestrator.run()
        
        # 状態ファイルが作成されているか確認
        assert state_file.exists()
        
        # 新しいOrchestratorインスタンスで再開
        orchestrator2 = Orchestrator(
            wbs_path=simple_wbs_file,
            workspace_dir=str(tmp_path),
            state_file=str(state_file),
            dry_run=True
        )
        
        # 残りのタスクが実行されることを確認
        results = await orchestrator2.run()
        assert len(results) == 1  # task-002のみ
        assert results[0].task_id == "task-002"