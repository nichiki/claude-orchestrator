import pytest
from pathlib import Path
import tempfile
import json
from src.core.artifact_manager import ArtifactManager, TaskArtifacts


class TestArtifactManager:
    
    @pytest.fixture
    def temp_workspace(self):
        """テスト用の一時ワークスペースを作成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            
            # タスクディレクトリと成果物を作成
            task1_dir = workspace / "task1"
            task1_dir.mkdir()
            (task1_dir / "models.py").write_text("# Task1 models")
            (task1_dir / "utils.py").write_text("# Task1 utils")
            
            task2_dir = workspace / "task2"
            task2_dir.mkdir()
            (task2_dir / "routes.py").write_text("# Task2 routes")
            (task2_dir / "models.py").write_text("# Task2 models")  # 競合ファイル
            
            task3_dir = workspace / "task3"
            task3_dir.mkdir()
            (task3_dir / "main.py").write_text("# Task3 main")
            
            yield workspace
    
    def test_register_task_artifacts(self, temp_workspace):
        """タスクの成果物登録をテスト"""
        manager = ArtifactManager()
        
        # Task1の成果物を登録
        task1_artifacts = manager.register_task_artifacts(
            "task1", "Create Models", temp_workspace / "task1"
        )
        
        assert task1_artifacts.task_id == "task1"
        assert task1_artifacts.task_name == "Create Models"
        assert len(task1_artifacts.artifacts) == 2
        files = task1_artifacts.get_files()
        assert "models.py" in files
        assert "utils.py" in files
        
        # registryに登録されていることを確認
        assert "task1" in manager.registry
        assert manager.registry["task1"] == task1_artifacts
    
    def test_get_task_artifacts(self, temp_workspace):
        """タスクIDによる成果物取得をテスト"""
        manager = ArtifactManager()
        
        # 複数タスクの成果物を登録
        manager.register_task_artifacts("task1", "Create Models", temp_workspace / "task1")
        manager.register_task_artifacts("task2", "Create Routes", temp_workspace / "task2")
        
        # Task1の成果物を取得
        task1_artifacts = manager.get_task_artifacts("task1")
        assert task1_artifacts is not None
        assert task1_artifacts.task_name == "Create Models"
        assert len(task1_artifacts.artifacts) == 2
        
        # 存在しないタスクID
        assert manager.get_task_artifacts("nonexistent") is None
    
    def test_get_tasks_by_file(self, temp_workspace):
        """ファイル名からタスクを検索"""
        manager = ArtifactManager()
        
        # 複数タスクの成果物を登録
        manager.register_task_artifacts("task1", "Create Models", temp_workspace / "task1")
        manager.register_task_artifacts("task2", "Create Routes", temp_workspace / "task2")
        manager.register_task_artifacts("task3", "Create Main", temp_workspace / "task3")
        
        # models.pyを生成したタスク（複数）
        model_tasks = manager.get_tasks_by_file("models.py")
        assert len(model_tasks) == 2
        assert "task1" in model_tasks
        assert "task2" in model_tasks
        
        # main.pyを生成したタスク（単一）
        main_tasks = manager.get_tasks_by_file("main.py")
        assert len(main_tasks) == 1
        assert "task3" in main_tasks
        
        # 存在しないファイル
        assert manager.get_tasks_by_file("nonexistent.py") == []
    
    def test_detect_file_conflicts(self, temp_workspace):
        """ファイル競合の検出をテスト"""
        manager = ArtifactManager()
        
        # 成果物を登録
        manager.register_task_artifacts("task1", "Create Models", temp_workspace / "task1")
        manager.register_task_artifacts("task2", "Create Routes", temp_workspace / "task2")
        manager.register_task_artifacts("task3", "Create Main", temp_workspace / "task3")
        
        # 競合を検出
        conflicts = manager.detect_file_conflicts()
        
        # models.pyが競合している
        assert "models.py" in conflicts
        assert set(conflicts["models.py"]) == {"task1", "task2"}
        
        # 他のファイルは競合していない
        assert "utils.py" not in conflicts
        assert "routes.py" not in conflicts
        assert "main.py" not in conflicts
    
    def test_get_dependencies_artifacts(self, temp_workspace):
        """依存タスクの成果物取得をテスト"""
        manager = ArtifactManager()
        
        # 成果物を登録
        manager.register_task_artifacts("task1", "Create Models", temp_workspace / "task1")
        manager.register_task_artifacts("task2", "Create Routes", temp_workspace / "task2")
        manager.register_task_artifacts("task3", "Create Main", temp_workspace / "task3")
        
        # Task1とTask2に依存するタスクの成果物を取得
        dep_artifacts = manager.get_dependencies_artifacts(["task1", "task2"])
        
        assert len(dep_artifacts) == 2
        assert "task1" in dep_artifacts
        assert "task2" in dep_artifacts
        assert len(dep_artifacts["task1"]) == 2  # artifactsリスト
        assert len(dep_artifacts["task2"]) == 2  # artifactsリスト
        
        # 存在しないタスクIDが含まれていても問題ない
        dep_artifacts = manager.get_dependencies_artifacts(["task1", "nonexistent"])
        assert len(dep_artifacts) == 1
        assert "task1" in dep_artifacts
    
    def test_persistence(self, temp_workspace):
        """レジストリの永続化と復元をテスト"""
        registry_file = temp_workspace / "artifact_registry.json"
        
        # 保存
        manager1 = ArtifactManager(storage_path=registry_file)
        manager1.register_task_artifacts("task1", "Create Models", temp_workspace / "task1")
        manager1.register_task_artifacts("task2", "Create Routes", temp_workspace / "task2")
        
        # ファイルが作成されたことを確認
        assert registry_file.exists()
        
        # 復元
        manager2 = ArtifactManager(storage_path=registry_file)
        
        # 内容が一致することを確認
        assert len(manager2.registry) == 2
        assert "task1" in manager2.registry
        assert "task2" in manager2.registry
        
        task1_artifacts = manager2.get_task_artifacts("task1")
        assert task1_artifacts.task_name == "Create Models"
        files = task1_artifacts.get_files()
        assert "models.py" in files
        assert "utils.py" in files
    
    def test_empty_task_directory(self):
        """空のタスクディレクトリの処理をテスト"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            empty_dir = workspace / "empty_task"
            empty_dir.mkdir()
            
            manager = ArtifactManager()
            artifacts = manager.register_task_artifacts(
                "empty_task", "Empty Task", empty_dir
            )
            
            assert artifacts.task_id == "empty_task"
            assert artifacts.task_name == "Empty Task"
            assert len(artifacts.artifacts) == 0
    
    def test_nested_files(self):
        """ネストされたディレクトリ構造の処理をテスト"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            task_dir = workspace / "nested_task"
            task_dir.mkdir()
            
            # ネストされたファイル構造を作成
            (task_dir / "main.py").write_text("# Main")
            subdir = task_dir / "submodule"
            subdir.mkdir()
            (subdir / "helper.py").write_text("# Helper")
            
            manager = ArtifactManager()
            artifacts = manager.register_task_artifacts(
                "nested_task", "Nested Task", task_dir
            )
            
            # rglob使用により、ネストされたファイルも含まれる
            assert len(artifacts.artifacts) == 2
            files = artifacts.get_files()
            assert "main.py" in files
            assert "helper.py" in files
    
    def test_base_file_saving(self):
        """ベースファイルの保存と取得のテスト"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir)
            manager = ArtifactManager(workspace_dir=workspace_dir)
            
            # 共有ワークスペースにファイルを作成
            shared_dir = workspace_dir / "shared"
            shared_dir.mkdir(parents=True, exist_ok=True)
            test_file = shared_dir / "test.py"
            test_file.write_text("original content")
            
            # タスクワークスペースを準備
            task_id = "test_task_1"
            task_workspace = manager.prepare_task_workspace(task_id)
            
            # ベースファイルが保存されているか確認
            base_file = manager._get_base_file(task_id, "test.py")
            assert base_file is not None
            assert base_file.exists()
            assert base_file.read_text() == "original content"
    
    def test_base_file_not_saved_for_empty_workspace(self):
        """空のワークスペースではベースファイルが保存されないことのテスト"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir)
            manager = ArtifactManager(workspace_dir=workspace_dir)
            
            # 空のワークスペースを準備
            task_id = "test_task_empty"
            task_workspace = manager.prepare_task_workspace(task_id)
            
            # ベースファイルディレクトリが作成されていないことを確認
            base_dir = manager.base_snapshots_dir / task_id
            assert not base_dir.exists()