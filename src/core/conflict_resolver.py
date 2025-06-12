"""
ファイル競合をClaude Codeを使って解決する
"""
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from datetime import datetime

from .task_executor import TaskExecutor, ExecutionResult

if TYPE_CHECKING:
    from .artifact_manager import ArtifactManager

logger = logging.getLogger(__name__)


@dataclass
class ConflictResolution:
    """競合解決の結果"""
    strategy: str  # "merged", "version", "failed"
    merged_file_path: Optional[Path] = None
    message: str = ""


class ConflictResolver:
    """Claude Codeを使った競合解決"""
    
    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.merge_workspace = workspace_dir / ".merge_tasks"
        self.merge_workspace.mkdir(exist_ok=True)
        
        # マージタスク実行用のexecutor
        self.executor = TaskExecutor(
            workspace_dir=str(self.merge_workspace),
            timeout=300  # 5分のタイムアウト
        )
    
    async def resolve_conflict(
        self,
        existing_file: Path,
        new_file: Path,
        task_id: str,
        artifact_manager: Optional['ArtifactManager'] = None
    ) -> ConflictResolution:
        """ファイル競合をClaude Codeで解決"""
        
        merge_task_id = f"merge_{existing_file.stem}_{int(datetime.now().timestamp())}"
        
        # マージ用のプロンプトを作成
        prompt = self._create_merge_prompt(existing_file, new_file)
        
        # Claudeでマージを実行
        logger.info(f"Attempting to merge {existing_file.name} using Claude Code")
        
        try:
            result = await self.executor.execute({
                "id": merge_task_id,
                "name": f"Merge {existing_file.name}",
                "prompt": prompt
            }, artifact_manager)
            
            if result.success:
                # マージ結果を確認
                return await self._check_merge_result(
                    result, merge_task_id, existing_file.name
                )
            else:
                logger.error(f"Merge task failed: {result.error}")
                return ConflictResolution(
                    strategy="version",
                    message=f"Merge task failed: {result.error}"
                )
                
        except Exception as e:
            logger.exception(f"Error during merge resolution: {e}")
            return ConflictResolution(
                strategy="version",
                message=f"Merge exception: {str(e)}"
            )
    
    def _create_merge_prompt(self, existing_file: Path, new_file: Path) -> str:
        """マージ用プロンプトを生成"""
        # ファイル内容を読み込む
        existing_content = existing_file.read_text()
        new_content = new_file.read_text()
        
        return f"""You are tasked with merging two versions of {existing_file.name}.

Please analyze both files and create an intelligent merge that:
1. Combines functionality from both versions
2. Resolves any conflicts appropriately
3. Maintains code quality and consistency

If the files serve fundamentally different purposes or cannot be meaningfully merged:
- Create a file named "CANNOT_MERGE.txt" explaining why
- Do NOT create the merged file

Otherwise:
- Create the merged version as {existing_file.name}
- Add a comment at the top explaining what was merged

=== Current version ({existing_file.name}) ===
{existing_content}

=== New version (from {new_file.parent.name}) ===
{new_content}

Please create the merged version now.
"""
    
    async def _check_merge_result(
        self,
        result: ExecutionResult,
        merge_task_id: str,
        filename: str
    ) -> ConflictResolution:
        """マージ結果を確認"""
        
        merge_task_dir = self.merge_workspace / merge_task_id
        
        # マージ不可ファイルをチェック
        cannot_merge_file = merge_task_dir / "CANNOT_MERGE.txt"
        if cannot_merge_file.exists():
            reason = cannot_merge_file.read_text()
            logger.info(f"Cannot merge {filename}: {reason}")
            return ConflictResolution(
                strategy="version",
                message=f"Cannot merge: {reason}"
            )
        
        # マージされたファイルをチェック
        merged_file = merge_task_dir / filename
        if merged_file.exists():
            logger.info(f"Successfully merged {filename}")
            return ConflictResolution(
                strategy="merged",
                merged_file_path=merged_file,
                message="Successfully merged by Claude Code"
            )
        
        # ファイルが見つからない
        logger.warning(f"Merge completed but no output file found for {filename}")
        return ConflictResolution(
            strategy="version",
            message="Merge completed but no output file found"
        )
    
    def cleanup_merge_workspace(self):
        """マージ作業ディレクトリをクリーンアップ"""
        import shutil
        if self.merge_workspace.exists():
            shutil.rmtree(self.merge_workspace)
            logger.info("Cleaned up merge workspace")
    
    async def resolve_three_way_conflict(
        self,
        base_file: Optional[Path],
        shared_file: Path,
        task_file: Path,
        task_id: str,
        artifact_manager: Optional['ArtifactManager'] = None
    ) -> ConflictResolution:
        """3-wayマージによる競合解決
        
        Args:
            base_file: ベースファイル（タスク開始時点のファイル）
            shared_file: 共有ワークスペースの現在のファイル
            task_file: タスクが生成したファイル
            task_id: タスクID
            
        Returns:
            ConflictResolution: マージ結果
        """
        
        merge_task_id = f"3way_merge_{shared_file.stem}_{int(datetime.now().timestamp())}"
        
        # 3-wayマージ用のプロンプトを作成
        prompt = self._create_three_way_merge_prompt(base_file, shared_file, task_file)
        
        # Claudeで3-wayマージを実行
        logger.info(f"Attempting 3-way merge for {shared_file.name} using Claude Code")
        
        try:
            result = await self.executor.execute({
                "id": merge_task_id,
                "name": f"3-way merge {shared_file.name}",
                "prompt": prompt
            }, artifact_manager)
            
            if result.success:
                # マージ結果を確認
                return await self._check_merge_result(
                    result, merge_task_id, shared_file.name
                )
            else:
                logger.error(f"3-way merge task failed: {result.error}")
                return ConflictResolution(
                    strategy="version",
                    message=f"3-way merge task failed: {result.error}"
                )
                
        except Exception as e:
            logger.exception(f"Error during 3-way merge resolution: {e}")
            return ConflictResolution(
                strategy="version",
                message=f"3-way merge exception: {str(e)}"
            )
    
    def _create_three_way_merge_prompt(
        self,
        base_file: Optional[Path],
        shared_file: Path,
        task_file: Path
    ) -> str:
        """3-wayマージ用プロンプトを生成"""
        
        # ファイル内容を読み込む
        base_content = base_file.read_text() if base_file and base_file.exists() else ""
        shared_content = shared_file.read_text()
        task_content = task_file.read_text()
        
        return f"""You are tasked with performing a 3-way merge for {shared_file.name}.

This is a 3-way merge scenario where:
- BASE: The original version both changes started from
- SHARED: Changes made by other tasks in the shared workspace
- TASK: Changes made by the current task

Please analyze all three versions and create an intelligent merge that:
1. Incorporates changes from both SHARED and TASK versions
2. Resolves conflicts by understanding the intent of each change
3. Maintains code quality and consistency
4. Preserves all functionality from both versions

If the changes are fundamentally incompatible:
- Create a file named "CANNOT_MERGE.txt" explaining why
- Do NOT create the merged file

Otherwise:
- Create the merged version as {shared_file.name}
- Add a comment at the top explaining the merge

=== BASE version (original) ===
{base_content if base_content else "# File did not exist in base version"}

=== SHARED version (from shared workspace) ===
{shared_content}

=== TASK version (from current task) ===
{task_content}

Please create the merged version now, incorporating changes from both SHARED and TASK versions.
"""