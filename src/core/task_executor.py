import asyncio
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING
from pathlib import Path
import json
import shutil
from datetime import datetime
import logging
import re

if TYPE_CHECKING:
    from .artifact_manager import ArtifactManager

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    task_id: str
    success: bool
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    artifacts: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    workspace: Optional[Path] = None  # タスクのワークスペースパス


class TaskExecutor:
    def __init__(self, workspace_dir: str = "./workspace", max_concurrent: int = 3, timeout: int = 3600):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(exist_ok=True)
        self.max_concurrent = max_concurrent
        self.timeout = timeout  # デフォルト1時間
        self._semaphore = asyncio.Semaphore(max_concurrent)
        
    def _build_command(self, task: Dict) -> List[str]:
        """Claude実行コマンドを構築"""
        # claudeコマンドのフルパスを使用
        claude_path = "/opt/homebrew/bin/claude"  # 一般的なHomebrewのパス
        if not Path(claude_path).exists():
            # Homebrewでない場合は通常のパス
            claude_path = "claude"
            
        # --print オプションで非対話的に実行
        cmd = [
            claude_path,
            "--print",
            task["prompt"]
        ]
        
        # 追加のオプションがあれば追加
        if task.get("context_files"):
            for file in task["context_files"]:
                cmd.extend(["-f", file])
                
        return cmd
    
    
    def _collect_artifacts(self, task_dir: Path) -> List[str]:
        """タスクディレクトリから生成物を収集"""
        artifacts = []
        
        for file_path in task_dir.rglob("*"):
            if file_path.is_file():
                relative_path = file_path.relative_to(task_dir)
                artifacts.append(str(relative_path))
                
        return artifacts
    
    async def execute(self, task: Dict, artifact_manager: Optional['ArtifactManager'] = None) -> ExecutionResult:
        """タスクを実行
        
        Args:
            task: タスク定義
            artifact_manager: 共有コンテキスト機能を使用する場合のArtifactManager
        """
        async with self._semaphore:  # 並列実行数を制限
            task_id = task["id"]
            start_time = datetime.now()
            
            try:
                # 作業ディレクトリを準備（常に共有コンテキストを使用）
                if artifact_manager:
                    task_dir = artifact_manager.prepare_task_workspace(task_id)
                    logger.info(f"Preparing workspace for task {task_id}")
                else:
                    # artifact_managerがない場合はエラー
                    raise ValueError("ArtifactManager is required for task execution")
                
                # コマンドを構築
                cmd = self._build_command(task)
                
                logger.info(f"Executing task {task_id}: {task['name']}")
                logger.debug(f"Command: {' '.join(cmd)}")
                
                # プロセスを実行
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(task_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                try:
                    # タイムアウト付きで実行
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.timeout
                    )
                    
                    # 実行結果を収集
                    execution_time = (datetime.now() - start_time).total_seconds()
                    artifacts = self._collect_artifacts(task_dir)
                    
                    result = ExecutionResult(
                        task_id=task_id,
                        success=(process.returncode == 0),
                        stdout=stdout.decode('utf-8', errors='replace'),
                        stderr=stderr.decode('utf-8', errors='replace'),
                        artifacts=artifacts,
                        execution_time=execution_time,
                        workspace=task_dir
                    )
                    
                    if process.returncode != 0:
                        result.error = f"Process exited with code {process.returncode}"
                        logger.error(f"Task {task_id} failed: {result.error}")
                        logger.error(f"stderr: {result.stderr}")
                        logger.error(f"stdout: {result.stdout}")
                    else:
                        logger.info(f"Task {task_id} completed successfully in {execution_time:.2f}s")
                        
                        # Claudeの標準出力を必ず保存（デバッグ用）
                        output_file = task_dir / "claude_output.txt"
                        output_file.write_text(result.stdout)
                        logger.debug(f"Saved Claude output to: {output_file}")
                        
                        # 再度アーティファクトを収集（Claudeが作成したファイル）
                        artifacts = self._collect_artifacts(task_dir)
                        result.artifacts = artifacts
                        
                        # 実際のファイルが作成されているかチェック（.claude以外、claude_output.txt以外）
                        real_files = [a for a in artifacts if '.claude' not in a and 'claude_output.txt' not in a]
                        
                        if real_files:
                            logger.info(f"Claude created {len(real_files)} files: {real_files}")
                        else:
                            # 実際のファイルがない場合のみ、出力からファイルを抽出を試みる
                            logger.info("No files created by Claude, attempting to extract from output")
                            self._extract_and_save_files(result.stdout, task_dir)
                            
                            # 再度アーティファクトを収集
                            artifacts = self._collect_artifacts(task_dir)
                            result.artifacts = artifacts
                            real_files = [a for a in artifacts if '.claude' not in a and 'claude_output.txt' not in a]
                            
                            if real_files:
                                logger.info(f"Extracted {len(real_files)} files from Claude output: {real_files}")
                            else:
                                logger.warning(f"No files could be extracted from Claude output")
                        
                except asyncio.TimeoutError:
                    # タイムアウト時はプロセスを強制終了
                    process.kill()
                    await process.wait()
                    
                    execution_time = (datetime.now() - start_time).total_seconds()
                    
                    result = ExecutionResult(
                        task_id=task_id,
                        success=False,
                        error=f"Task timeout after {self.timeout}s",
                        execution_time=execution_time,
                        workspace=task_dir
                    )
                    logger.error(f"Task {task_id} timed out after {self.timeout}s")
                    
            except Exception as e:
                # その他のエラー
                execution_time = (datetime.now() - start_time).total_seconds()
                
                result = ExecutionResult(
                    task_id=task_id,
                    success=False,
                    error=str(e),
                    execution_time=execution_time
                )
                logger.exception(f"Task {task_id} failed with exception")
                
            return result
    
    async def execute_batch(self, tasks: List[Dict]) -> List[ExecutionResult]:
        """複数のタスクをバッチ実行"""
        logger.info(f"Starting batch execution of {len(tasks)} tasks")
        
        # 全タスクを並列実行（max_concurrentで制限）
        results = await asyncio.gather(
            *[self.execute(task) for task in tasks],
            return_exceptions=True
        )
        
        # 例外をExecutionResultに変換
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    ExecutionResult(
                        task_id=tasks[i]["id"],
                        success=False,
                        error=str(result)
                    )
                )
            else:
                final_results.append(result)
                
        successful = sum(1 for r in final_results if r.success)
        logger.info(f"Batch execution completed: {successful}/{len(tasks)} tasks succeeded")
        
        return final_results
    
    def cleanup_workspace(self, task_id: Optional[str] = None):
        """作業ディレクトリをクリーンアップ"""
        if task_id:
            task_dir = self.workspace_dir / task_id
            if task_dir.exists():
                shutil.rmtree(task_dir)
                logger.info(f"Cleaned up workspace for task {task_id}")
        else:
            # 全体をクリーンアップ
            if self.workspace_dir.exists():
                shutil.rmtree(self.workspace_dir)
                self.workspace_dir.mkdir()
                logger.info("Cleaned up entire workspace")
    
    def _extract_and_save_files(self, stdout: str, task_dir: Path):
        """標準出力からコードブロックを抽出してファイルに保存"""
        # Markdownのコードブロックパターン
        # ```python filename.py または ```filename.py の形式を検出
        code_block_pattern = r'```(?:[\w]+)?\s*(?:# )?(\S+\.[\w]+)?\n(.*?)```'
        
        matches = re.findall(code_block_pattern, stdout, re.DOTALL)
        
        for filename, content in matches:
            if filename:
                # ファイル名が指定されている場合
                file_path = task_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content.strip())
                logger.info(f"Saved file: {file_path}")
        
        # ファイル名なしのコードブロックも検出（最初に見つかったものを推測）
        if not matches:
            # プロンプトからファイル名を推測
            if "models.py" in stdout:
                filename = "models.py"
            elif "routes.py" in stdout:
                filename = "routes.py"
            elif "main.py" in stdout:
                filename = "main.py"
            elif ".md" in stdout:
                # Markdownファイルの推測
                if "project_structure" in stdout.lower():
                    filename = "project_structure.md"
                elif "api_spec" in stdout.lower():
                    filename = "api_spec.md"
                else:
                    filename = "output.md"
            else:
                filename = "output.txt"
            
            # 既存ファイルを上書きしないように、extracted_プレフィックスを付ける
            file_path = task_dir / f"extracted_{filename}"
            file_path.write_text(stdout)
            logger.info(f"Saved entire output to: {file_path}")