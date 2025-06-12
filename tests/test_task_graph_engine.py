import pytest
from pathlib import Path
from src.core import TaskGraphEngine, TaskStatus
from src.core.task_graph_engine import Task
import yaml
import tempfile


class TestTaskGraphEngine:
    @pytest.fixture
    def simple_wbs(self):
        """シンプルなWBS構造を作成"""
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
                            "name": "タスク1",
                            "dependencies": []
                        },
                        {
                            "id": "task-002", 
                            "name": "タスク2",
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
    def complex_wbs(self):
        """複雑な依存関係を持つWBS"""
        wbs_data = {
            "project": {
                "name": "複雑なプロジェクト"
            },
            "phases": [
                {
                    "id": "phase1",
                    "tasks": [
                        {
                            "id": "task-001",
                            "name": "タスクA",
                            "dependencies": []
                        },
                        {
                            "id": "task-002",
                            "name": "タスクB", 
                            "dependencies": []
                        },
                        {
                            "id": "task-003",
                            "name": "タスクC",
                            "dependencies": ["task-001", "task-002"]
                        }
                    ]
                },
                {
                    "id": "phase2",
                    "depends_on_phase": "phase1",
                    "tasks": [
                        {
                            "id": "task-004",
                            "name": "タスクD",
                            "dependencies": []
                        }
                    ]
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(wbs_data, f)
            return f.name

    def test_load_simple_wbs(self, simple_wbs):
        """WBSファイルを正しく読み込めるか"""
        engine = TaskGraphEngine(simple_wbs)
        
        assert len(engine.tasks) == 2
        assert "task-001" in engine.tasks
        assert "task-002" in engine.tasks
        assert engine.tasks["task-001"].name == "タスク1"
        assert engine.tasks["task-002"].dependencies == ["task-001"]

    def test_get_executable_tasks_initial(self, simple_wbs):
        """初期状態で実行可能なタスクを取得"""
        engine = TaskGraphEngine(simple_wbs)
        executable = engine.get_executable_tasks()
        
        assert len(executable) == 1
        assert executable[0].id == "task-001"

    def test_get_executable_tasks_parallel(self, complex_wbs):
        """並列実行可能なタスクを正しく検出"""
        engine = TaskGraphEngine(complex_wbs)
        executable = engine.get_executable_tasks()
        
        assert len(executable) == 2
        task_ids = {t.id for t in executable}
        assert task_ids == {"task-001", "task-002"}

    def test_update_task_status(self, simple_wbs):
        """タスクステータスの更新"""
        engine = TaskGraphEngine(simple_wbs)
        
        engine.update_task_status("task-001", TaskStatus.IN_PROGRESS)
        assert engine.tasks["task-001"].status == TaskStatus.IN_PROGRESS
        
        engine.update_task_status("task-001", TaskStatus.COMPLETED)
        assert engine.tasks["task-001"].status == TaskStatus.COMPLETED

    def test_get_executable_after_completion(self, simple_wbs):
        """タスク完了後の実行可能タスク取得"""
        engine = TaskGraphEngine(simple_wbs)
        
        # task-001を完了
        engine.update_task_status("task-001", TaskStatus.COMPLETED)
        
        executable = engine.get_executable_tasks()
        assert len(executable) == 1
        assert executable[0].id == "task-002"

    def test_phase_dependency(self, complex_wbs):
        """フェーズ間の依存関係処理"""
        engine = TaskGraphEngine(complex_wbs)
        
        # Phase1のタスクを全て完了
        engine.update_task_status("task-001", TaskStatus.COMPLETED)
        engine.update_task_status("task-002", TaskStatus.COMPLETED)
        engine.update_task_status("task-003", TaskStatus.COMPLETED)
        
        # Phase2のタスクが実行可能になる
        executable = engine.get_executable_tasks()
        assert any(t.id == "task-004" for t in executable)

    def test_circular_dependency_detection(self):
        """循環依存の検出"""
        wbs_data = {
            "project": {"name": "循環依存テスト"},
            "phases": [{
                "id": "phase1",
                "tasks": [
                    {"id": "task-001", "name": "A", "dependencies": ["task-003"]},
                    {"id": "task-002", "name": "B", "dependencies": ["task-001"]},
                    {"id": "task-003", "name": "C", "dependencies": ["task-002"]}
                ]
            }]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(wbs_data, f)
            
            with pytest.raises(ValueError, match="Circular dependency"):
                TaskGraphEngine(f.name)

    def test_get_task_status(self, simple_wbs):
        """タスクステータスの取得"""
        engine = TaskGraphEngine(simple_wbs)
        
        status = engine.get_task_status("task-001")
        assert status == TaskStatus.PENDING
        
        engine.update_task_status("task-001", TaskStatus.IN_PROGRESS)
        status = engine.get_task_status("task-001")
        assert status == TaskStatus.IN_PROGRESS

    def test_is_all_tasks_completed(self, simple_wbs):
        """全タスク完了の判定"""
        engine = TaskGraphEngine(simple_wbs)
        
        assert not engine.is_all_tasks_completed()
        
        engine.update_task_status("task-001", TaskStatus.COMPLETED)
        assert not engine.is_all_tasks_completed()
        
        engine.update_task_status("task-002", TaskStatus.COMPLETED)
        assert engine.is_all_tasks_completed()

    def test_get_progress_summary(self, complex_wbs):
        """進捗サマリーの取得"""
        engine = TaskGraphEngine(complex_wbs)
        
        summary = engine.get_progress_summary()
        assert summary["total"] == 4
        assert summary["pending"] == 4
        assert summary["in_progress"] == 0
        assert summary["completed"] == 0
        
        engine.update_task_status("task-001", TaskStatus.IN_PROGRESS)
        engine.update_task_status("task-002", TaskStatus.COMPLETED)
        
        summary = engine.get_progress_summary()
        assert summary["pending"] == 2
        assert summary["in_progress"] == 1
        assert summary["completed"] == 1