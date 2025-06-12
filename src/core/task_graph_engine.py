from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
import yaml
from pathlib import Path


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    name: str
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    phase_id: Optional[str] = None


class TaskGraphEngine:
    def __init__(self, wbs_path: str):
        self.tasks: Dict[str, Task] = {}
        self.phase_dependencies: Dict[str, str] = {}  # phase_id -> depends_on_phase
        self._load_wbs(wbs_path)
        self._validate_dependencies()
    
    def _load_wbs(self, wbs_path: str):
        """WBSファイルからタスクグラフを構築"""
        with open(wbs_path, 'r', encoding='utf-8') as f:
            wbs_data = yaml.safe_load(f)
        
        for phase in wbs_data.get('phases', []):
            phase_id = phase['id']
            
            # フェーズ間依存を記録
            if 'depends_on_phase' in phase:
                self.phase_dependencies[phase_id] = phase['depends_on_phase']
            
            # タスクを読み込み
            for task_data in phase.get('tasks', []):
                task = Task(
                    id=task_data['id'],
                    name=task_data['name'],
                    dependencies=task_data.get('dependencies', []),
                    phase_id=phase_id
                )
                self.tasks[task.id] = task
    
    def _validate_dependencies(self):
        """循環依存のチェック"""
        def has_cycle(task_id: str, visited: Set[str], rec_stack: Set[str]) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)
            
            task = self.tasks.get(task_id)
            if task:
                for dep_id in task.dependencies:
                    if dep_id not in visited:
                        if has_cycle(dep_id, visited, rec_stack):
                            return True
                    elif dep_id in rec_stack:
                        return True
            
            rec_stack.remove(task_id)
            return False
        
        visited = set()
        for task_id in self.tasks:
            if task_id not in visited:
                if has_cycle(task_id, visited, set()):
                    raise ValueError(f"Circular dependency detected involving task {task_id}")
    
    def _is_phase_ready(self, phase_id: str) -> bool:
        """フェーズが実行可能かチェック"""
        if phase_id not in self.phase_dependencies:
            return True
        
        depends_on = self.phase_dependencies[phase_id]
        # 依存フェーズの全タスクが完了しているか
        for task in self.tasks.values():
            if task.phase_id == depends_on and task.status != TaskStatus.COMPLETED:
                return False
        return True
    
    def get_executable_tasks(self) -> List[Task]:
        """現在実行可能なタスクのリストを返す"""
        executable = []
        
        for task in self.tasks.values():
            # すでに実行中または完了済みはスキップ
            if task.status != TaskStatus.PENDING:
                continue
            
            # フェーズが準備できていない場合はスキップ
            if task.phase_id and not self._is_phase_ready(task.phase_id):
                continue
            
            # 全ての依存タスクが完了しているかチェック
            all_deps_completed = all(
                self.tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
                if dep_id in self.tasks
            )
            
            if all_deps_completed:
                executable.append(task)
        
        return executable
    
    def update_task_status(self, task_id: str, status: TaskStatus):
        """タスクのステータスを更新"""
        if task_id in self.tasks:
            self.tasks[task_id].status = status
        else:
            raise ValueError(f"Task {task_id} not found")
    
    def get_task_status(self, task_id: str) -> TaskStatus:
        """タスクのステータスを取得"""
        if task_id in self.tasks:
            return self.tasks[task_id].status
        else:
            raise ValueError(f"Task {task_id} not found")
    
    def is_all_tasks_completed(self) -> bool:
        """全てのタスクが完了したかチェック"""
        return all(
            task.status == TaskStatus.COMPLETED
            for task in self.tasks.values()
        )
    
    def get_progress_summary(self) -> Dict[str, int]:
        """進捗のサマリーを取得"""
        summary = {
            "total": len(self.tasks),
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0
        }
        
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING:
                summary["pending"] += 1
            elif task.status == TaskStatus.IN_PROGRESS:
                summary["in_progress"] += 1
            elif task.status == TaskStatus.COMPLETED:
                summary["completed"] += 1
            elif task.status == TaskStatus.FAILED:
                summary["failed"] += 1
        
        return summary