import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any

from .task_graph_engine import TaskGraphEngine, TaskStatus
from .task_executor import TaskExecutor, ExecutionResult
from .artifact_manager import ArtifactManager
from .conflict_resolver import ConflictResolver


logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        wbs_path: str,
        workspace_dir: str = "./workspace",
        state_file: Optional[str] = None,
        max_concurrent: int = 3,
        dry_run: bool = False,
        fail_fast: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        self.wbs_path = wbs_path
        self.workspace_dir = Path(workspace_dir)
        self.state_file = Path(state_file) if state_file else None
        self.max_concurrent = max_concurrent
        self.dry_run = dry_run
        self.fail_fast = fail_fast
        self.progress_callback = progress_callback
        
        # コンポーネントの初期化
        self.graph_engine = TaskGraphEngine(wbs_path)
        self.task_executor = TaskExecutor(
            workspace_dir=str(self.workspace_dir),
            max_concurrent=max_concurrent
        )
        
        # 実行結果の記録
        self.results: List[ExecutionResult] = []
        
        # アーティファクトマネージャの初期化
        artifact_registry_path = self.workspace_dir / "artifact_registry.json"
        self.artifact_manager = ArtifactManager(
            storage_path=artifact_registry_path,
            workspace_dir=self.workspace_dir
        )
        
        # 競合解決リゾルバーの初期化
        self.conflict_resolver = ConflictResolver(workspace_dir=self.workspace_dir)
        
        # テスト用のフラグ
        self._simulate_error: Optional[str] = None
        self._max_tasks: Optional[int] = None
        
    def _load_state(self):
        """保存された状態を読み込む"""
        if self.state_file and self.state_file.exists():
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                
            # タスクの状態を復元
            for task_id, status_str in state.get("task_status", {}).items():
                if task_id in self.graph_engine.tasks:
                    status = TaskStatus(status_str)
                    self.graph_engine.update_task_status(task_id, status)
                    
            logger.info(f"State loaded from {self.state_file}")
            
    def _save_state(self):
        """現在の状態を保存"""
        if self.state_file:
            state = {
                "timestamp": datetime.now().isoformat(),
                "task_status": {
                    task_id: task.status.value
                    for task_id, task in self.graph_engine.tasks.items()
                }
            }
            
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
                
    def _emit_progress(self, event_type: str, **kwargs):
        """進捗状況を通知"""
        if self.progress_callback:
            update = {
                "type": event_type,
                "timestamp": datetime.now().isoformat(),
                **kwargs
            }
            self.progress_callback(update)
            
    async def _execute_task(self, task_dict: Dict[str, Any]) -> ExecutionResult:
        """単一タスクを実行"""
        task_id = task_dict["id"]
        
        # 進捗通知
        self._emit_progress("task_started", task_id=task_id, task_name=task_dict["name"])
        
        # タスクステータスを更新
        self.graph_engine.update_task_status(task_id, TaskStatus.IN_PROGRESS)
        self._save_state()
        
        if self.dry_run:
            # ドライランモード：実際の実行はスキップ
            await asyncio.sleep(0.1)  # 実行をシミュレート
            
            # エラーシミュレーション（テスト用）
            if self._simulate_error == task_id:
                result = ExecutionResult(
                    task_id=task_id,
                    success=False,
                    error="Simulated error"
                )
            else:
                result = ExecutionResult(
                    task_id=task_id,
                    success=True,
                    stdout=f"Dry run: {task_dict['name']} completed"
                )
        else:
            # 実際の実行（常にArtifactManagerを使用）
            result = await self.task_executor.execute(task_dict, self.artifact_manager)
            
        # 結果に基づいてステータスを更新
        if result.success:
            self.graph_engine.update_task_status(task_id, TaskStatus.COMPLETED)
            self._emit_progress("task_completed", task_id=task_id)
            
            # 成果物を登録（ドライランでない場合）
            if not self.dry_run and result.artifacts and result.workspace:
                # タスク結果を共有ワークスペースに統合（常に実行）
                integration_result = await self.artifact_manager.integrate_task_results(
                    task_id=task_id,
                    task_workspace=result.workspace,
                    conflict_resolver=self.conflict_resolver
                )
                logger.info(f"Integrated task {task_id} results: "
                          f"{integration_result['new']} new, "
                          f"{integration_result['modified']} modified, "
                          f"{integration_result.get('conflict', 0)} conflicts")
        else:
            self.graph_engine.update_task_status(task_id, TaskStatus.FAILED)
            self._emit_progress("task_failed", task_id=task_id, error=result.error)
            
        self._save_state()
        return result
        
    async def run(self) -> List[ExecutionResult]:
        """プロジェクト全体を実行"""
        logger.info(f"Starting orchestration for project: {self.wbs_path}")
        
        # 状態を読み込む
        self._load_state()
        
        # 初期進捗を通知
        summary = self.graph_engine.get_progress_summary()
        self._emit_progress("project_started", summary=summary)
        
        executed_count = 0
        
        try:
            while not self.graph_engine.is_all_tasks_completed():
                # テスト用の制限
                if self._max_tasks and executed_count >= self._max_tasks:
                    break
                    
                # 実行可能なタスクを取得
                executable_tasks = self.graph_engine.get_executable_tasks()
                
                if not executable_tasks:
                    # デッドロックまたは全タスク失敗
                    failed_tasks = [
                        t for t in self.graph_engine.tasks.values()
                        if t.status == TaskStatus.FAILED
                    ]
                    if failed_tasks:
                        error_msg = f"Cannot proceed: {len(failed_tasks)} tasks failed"
                        logger.error(error_msg)
                        if self.fail_fast:
                            raise RuntimeError(error_msg)
                    break
                    
                # 並列実行
                batch_results = await asyncio.gather(
                    *[self._execute_task({
                        "id": task.id,
                        "name": task.name,
                        "prompt": self._get_task_prompt(task.id)
                    }) for task in executable_tasks],
                    return_exceptions=True
                )
                
                # 結果を処理
                for result in batch_results:
                    if isinstance(result, Exception):
                        logger.exception("Task execution failed with exception", exc_info=result)
                        if self.fail_fast:
                            raise result
                    else:
                        self.results.append(result)
                        executed_count += 1
                        
                        # エラーチェック
                        if not result.success and self.fail_fast:
                            raise RuntimeError(f"Task {result.task_id} failed: {result.error}")
                            
                # 進捗を更新
                summary = self.graph_engine.get_progress_summary()
                self._emit_progress("progress_update", summary=summary)
                
        finally:
            # 最終状態を保存
            self._save_state()
            
        # 完了通知
        summary = self.graph_engine.get_progress_summary()
        self._emit_progress("project_completed", summary=summary)
        
        logger.info(f"Orchestration completed. {summary['completed']}/{summary['total']} tasks succeeded")
        
        # 成果物の統合
        if summary['completed'] > 0:
            await self._integrate_artifacts()
            
            # アーティファクトマネージャのサマリーを表示
            artifact_summary = self.artifact_manager.get_summary()
            logger.info(f"Artifact summary: {artifact_summary}")
        
        return self.results
        
    def _get_task_prompt(self, task_id: str) -> str:
        """タスクIDからプロンプトを取得（WBSから読み込む）"""
        # 簡易実装：WBSファイルを再度読み込んでプロンプトを取得
        import yaml
        with open(self.wbs_path, 'r') as f:
            wbs_data = yaml.safe_load(f)
            
        for phase in wbs_data.get('phases', []):
            for task in phase.get('tasks', []):
                if task['id'] == task_id:
                    return task.get('prompt', f"Execute task: {task['name']}")
                    
        return f"Execute task: {task_id}"
        
    def get_status_report(self) -> Dict[str, Any]:
        """現在の実行状況レポートを生成"""
        summary = self.graph_engine.get_progress_summary()
        
        # タスクごとの詳細
        task_details = []
        for task_id, task in self.graph_engine.tasks.items():
            result = next((r for r in self.results if r.task_id == task_id), None)
            
            detail = {
                "id": task_id,
                "name": task.name,
                "status": task.status.value,
                "phase": task.phase_id
            }
            
            if result:
                detail.update({
                    "execution_time": result.execution_time,
                    "artifacts": result.artifacts,
                    "error": result.error if not result.success else None
                })
                
            task_details.append(detail)
            
        return {
            "summary": summary,
            "tasks": task_details,
            "workspace": str(self.workspace_dir)
        }
    
    async def _integrate_artifacts(self):
        """各タスクの成果物を統合ディレクトリに集約（ArtifactManager経由）"""
        integrated_dir = self.workspace_dir / "integrated"
        integrated_dir.mkdir(exist_ok=True)
        
        logger.info("Starting artifact integration...")
        
        # 各タスクの成果物をコピー
        copied_files = []
        versioned_files = []
        
        for result in self.results:
            if result.success and result.artifacts:
                task_dir = self.workspace_dir / result.task_id
                
                for artifact in result.artifacts:
                    # .claude ディレクトリ内のファイルはスキップ
                    if '.claude' in artifact:
                        continue
                        
                    source_file = task_dir / artifact
                    if source_file.exists():
                        # ArtifactManagerを使用して統合（競合時はClaude Codeでマージを試みる）
                        actual_path = await self.artifact_manager.integrate_artifact(
                            source_path=source_file,
                            dest_dir=integrated_dir,
                            task_id=result.task_id,
                            conflict_resolver=self.conflict_resolver
                        )
                        
                        # 実際に保存されたファイル名を記録
                        actual_name = actual_path.name
                        if actual_name != source_file.name:
                            versioned_files.append(f"{source_file.name} -> {actual_name}")
                        
                        copied_files.append(str(actual_name))
        
        if copied_files:
            logger.info(f"Integration completed. {len(copied_files)} files integrated to {integrated_dir}")
            
            if versioned_files:
                logger.warning(f"File conflicts resolved by versioning: {versioned_files}")
            
            # READMEを生成
            readme_content = f"""# Integrated Project Artifacts

This directory contains all artifacts generated by the AI-driven project execution.

## Generated Files:
"""
            for file in sorted(set(copied_files)):
                readme_content += f"- {file}\n"
            
            if versioned_files:
                readme_content += "\n## File Conflicts (Versioned):\n"
                for conflict in versioned_files:
                    readme_content += f"- {conflict}\n"
            
            readme_content += f"\n## Generation Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            
            readme_file = integrated_dir / "README.md"
            readme_file.write_text(readme_content)
            logger.info(f"Created integration README: {readme_file}")
        else:
            logger.warning("No artifacts found to integrate")
            
