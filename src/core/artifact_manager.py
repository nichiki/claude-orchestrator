"""
成果物管理システム
タスクの実行結果として生成されたファイルを追跡・管理する
共有コンテキスト機能をサポート
"""
import json
import hashlib
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .conflict_resolver import ConflictResolver

logger = logging.getLogger(__name__)


@dataclass
class Artifact:
    """単一の成果物"""
    filename: str
    path: str  # タスクディレクトリからの相対パス
    size: int
    hash: str
    created_at: str
    task_id: str


@dataclass
class FileMetadata:
    """ファイルのメタデータ（スナップショット用）"""
    hash: str
    size: int
    mtime: float


@dataclass
class TaskArtifacts:
    """タスクの成果物セット"""
    task_id: str
    task_name: str
    completed_at: str
    artifacts: List[Artifact] = field(default_factory=list)
    
    def add_artifact(self, artifact: Artifact):
        self.artifacts.append(artifact)
        
    def get_files(self) -> List[str]:
        """ファイル名のリストを返す"""
        return [a.filename for a in self.artifacts]


class ArtifactManager:
    """成果物管理システム"""
    
    def __init__(self, storage_path: Optional[Path] = None, workspace_dir: Optional[Path] = None):
        self.registry: Dict[str, TaskArtifacts] = {}
        self.file_index: Dict[str, List[str]] = {}  # filename -> [task_ids]
        self.storage_path = storage_path
        self.workspace_dir = workspace_dir or Path("workspace")
        self.shared_workspace = self.workspace_dir / "shared"
        self.task_snapshots: Dict[str, Dict[str, FileMetadata]] = {}  # task_id -> snapshot
        self.base_snapshots_dir = self.workspace_dir / "base_snapshots"  # ベースファイル保存用ディレクトリ
        
        if storage_path and storage_path.exists():
            self._load_registry()
    
    def register_task_artifacts(self, task_id: str, task_name: str, 
                              task_dir: Path, exclude_patterns: List[str] = None) -> TaskArtifacts:
        """タスクの成果物を登録"""
        if exclude_patterns is None:
            exclude_patterns = ['.claude', '__pycache__', '.git']
            
        task_artifacts = TaskArtifacts(
            task_id=task_id,
            task_name=task_name,
            completed_at=datetime.now().isoformat()
        )
        
        # ディレクトリ内の全ファイルを走査
        for file_path in task_dir.rglob("*"):
            if file_path.is_file():
                # 除外パターンチェック
                if any(pattern in str(file_path) for pattern in exclude_patterns):
                    continue
                    
                relative_path = file_path.relative_to(task_dir)
                
                artifact = Artifact(
                    filename=file_path.name,
                    path=str(relative_path),
                    size=file_path.stat().st_size,
                    hash=self._calculate_hash(file_path),
                    created_at=datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                    task_id=task_id
                )
                
                task_artifacts.add_artifact(artifact)
                
                # ファイルインデックスを更新
                if artifact.filename not in self.file_index:
                    self.file_index[artifact.filename] = []
                self.file_index[artifact.filename].append(task_id)
                
                logger.info(f"Registered artifact: {artifact.filename} from task {task_id}")
        
        self.registry[task_id] = task_artifacts
        self._save_registry()
        
        return task_artifacts
    
    def get_task_artifacts(self, task_id: str) -> Optional[TaskArtifacts]:
        """特定タスクの成果物を取得"""
        return self.registry.get(task_id)
    
    def get_tasks_by_file(self, filename: str) -> List[str]:
        """特定のファイル名を生成したタスクのリストを取得"""
        return self.file_index.get(filename, [])
    
    def detect_file_conflicts(self) -> Dict[str, List[str]]:
        """同じファイル名を生成した複数のタスクを検出"""
        conflicts = {}
        for filename, task_ids in self.file_index.items():
            if len(task_ids) > 1:
                conflicts[filename] = task_ids
        return conflicts
    
    def get_artifact_by_name(self, filename: str, task_id: Optional[str] = None) -> List[Artifact]:
        """ファイル名で成果物を検索"""
        artifacts = []
        
        if task_id:
            # 特定タスクから検索
            task_artifacts = self.registry.get(task_id)
            if task_artifacts:
                artifacts = [a for a in task_artifacts.artifacts if a.filename == filename]
        else:
            # 全タスクから検索
            for task_artifacts in self.registry.values():
                artifacts.extend([a for a in task_artifacts.artifacts if a.filename == filename])
                
        return artifacts
    
    def get_dependencies_artifacts(self, task_dependencies: List[str]) -> Dict[str, List[Artifact]]:
        """依存タスクの成果物を取得"""
        dependencies_artifacts = {}
        
        for dep_id in task_dependencies:
            if dep_id in self.registry:
                dependencies_artifacts[dep_id] = self.registry[dep_id].artifacts
                
        return dependencies_artifacts
    
    def _calculate_hash(self, file_path: Path) -> str:
        """ファイルのハッシュ値を計算"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()[:16]  # 短縮版
    
    def _save_registry(self):
        """レジストリをファイルに保存"""
        if not self.storage_path:
            return
            
        data = {
            "registry": {
                task_id: {
                    "task_id": ta.task_id,
                    "task_name": ta.task_name,
                    "completed_at": ta.completed_at,
                    "artifacts": [asdict(a) for a in ta.artifacts]
                }
                for task_id, ta in self.registry.items()
            },
            "file_index": self.file_index
        }
        
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, 'w') as f:
            json.dump(data, f, indent=2)
            
        logger.debug(f"Registry saved to {self.storage_path}")
    
    def _load_registry(self):
        """レジストリをファイルから読み込み"""
        if not self.storage_path or not self.storage_path.exists():
            return
            
        with open(self.storage_path, 'r') as f:
            data = json.load(f)
            
        # レジストリを復元
        for task_id, task_data in data.get("registry", {}).items():
            task_artifacts = TaskArtifacts(
                task_id=task_data["task_id"],
                task_name=task_data["task_name"],
                completed_at=task_data["completed_at"]
            )
            
            for artifact_data in task_data["artifacts"]:
                artifact = Artifact(**artifact_data)
                task_artifacts.add_artifact(artifact)
                
            self.registry[task_id] = task_artifacts
            
        self.file_index = data.get("file_index", {})
        
        logger.info(f"Registry loaded from {self.storage_path}")
    
    def get_summary(self) -> Dict:
        """登録された成果物のサマリーを取得"""
        total_artifacts = sum(len(ta.artifacts) for ta in self.registry.values())
        total_size = sum(a.size for ta in self.registry.values() for a in ta.artifacts)
        
        return {
            "total_tasks": len(self.registry),
            "total_artifacts": total_artifacts,
            "total_size": total_size,
            "file_conflicts": len(self.detect_file_conflicts()),
            "unique_files": len(self.file_index)
        }
    
    async def integrate_artifact(
        self, 
        source_path: Path, 
        dest_dir: Path, 
        task_id: str,
        conflict_resolver: Optional['ConflictResolver'] = None
    ) -> Path:
        """
        成果物を統合ディレクトリに移動（競合時は解決を試みる）
        
        Args:
            source_path: 移動元のファイルパス
            dest_dir: 統合先ディレクトリ
            task_id: タスクID
            conflict_resolver: 競合解決に使用するリゾルバー
            
        Returns:
            実際に保存されたパス
        """
        import shutil
        
        dest_dir.mkdir(parents=True, exist_ok=True)
        original_dest = dest_dir / source_path.name
        
        # 競合チェック
        if original_dest.exists():
            if conflict_resolver:
                # Claude Codeによるマージを試みる
                logger.info(f"Attempting to merge {source_path.name} using Claude Code...")
                resolution = await conflict_resolver.resolve_conflict(
                    existing_file=original_dest,
                    new_file=source_path,
                    task_id=task_id
                )
                
                if resolution.strategy == "merged" and resolution.merged_file_path:
                    # マージ成功 - マージ結果で上書き
                    shutil.copy2(resolution.merged_file_path, original_dest)
                    logger.info(
                        f"Successfully merged {source_path.name}: {resolution.message}"
                    )
                    return original_dest
                else:
                    # マージ失敗 - バージョニング
                    logger.info(f"Merge failed: {resolution.message}")
            
            # バージョニング処理
            stem = source_path.stem
            suffix = source_path.suffix
            versioned_name = f"{stem}_{task_id}{suffix}"
            dest_path = dest_dir / versioned_name
            
            logger.warning(
                f"File conflict detected: {source_path.name} already exists. "
                f"Saving as {versioned_name} from task {task_id}"
            )
        else:
            dest_path = original_dest
        
        # ファイルをコピー
        shutil.copy2(source_path, dest_path)
        logger.info(f"Integrated: {source_path.name} -> {dest_path.name}")
        
        return dest_path
    
    def _create_snapshot(self, directory: Path) -> Dict[str, FileMetadata]:
        """ディレクトリのスナップショットを作成
        
        Args:
            directory: スナップショットを作成するディレクトリ
            
        Returns:
            ファイルパス -> メタデータのマッピング
        """
        snapshot = {}
        
        if not directory.exists():
            return snapshot
            
        for file_path in directory.rglob("*"):
            if file_path.is_file():
                # 除外パターン
                if any(pattern in str(file_path) for pattern in ['.git', '__pycache__', '.claude']):
                    continue
                    
                try:
                    stat = file_path.stat()
                    rel_path = file_path.relative_to(directory)
                    
                    snapshot[str(rel_path)] = FileMetadata(
                        hash=self._calculate_hash(file_path),
                        size=stat.st_size,
                        mtime=stat.st_mtime
                    )
                except Exception as e:
                    logger.warning(f"Failed to snapshot {file_path}: {e}")
                    
        return snapshot
    
    def _save_base_files(self, task_id: str, workspace: Path):
        """タスク開始時のファイル状態を保存
        
        Args:
            task_id: タスクID
            workspace: タスクワークスペース
        """
        # 保存すべきファイルがあるかチェック
        files_to_save = []
        for file_path in workspace.rglob("*"):
            if file_path.is_file():
                # 除外パターン
                if any(pattern in str(file_path) for pattern in ['.git', '__pycache__', '.claude']):
                    continue
                files_to_save.append(file_path)
        
        # ファイルがない場合は何もしない
        if not files_to_save:
            logger.debug(f"No files to save as base for task {task_id}")
            return
            
        task_base_dir = self.base_snapshots_dir / task_id
        task_base_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイルをコピー
        for file_path in files_to_save:
            rel_path = file_path.relative_to(workspace)
            base_file_path = task_base_dir / rel_path
            base_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # ファイルをコピー
            shutil.copy2(file_path, base_file_path)
            logger.debug(f"Saved base file: {rel_path}")
                
        logger.info(f"Saved {len(files_to_save)} base files for task {task_id} in {task_base_dir}")
    
    def _get_base_file(self, task_id: str, relative_path: str) -> Optional[Path]:
        """保存されたベースファイルを取得
        
        Args:
            task_id: タスクID
            relative_path: ワークスペースからの相対パス
            
        Returns:
            ベースファイルのパス（存在しない場合はNone）
        """
        base_file_path = self.base_snapshots_dir / task_id / relative_path
        if base_file_path.exists():
            return base_file_path
        return None
    
    def prepare_task_workspace(self, task_id: str) -> Path:
        """タスク用ワークスペースを準備（共有コンテキストのコピー含む）
        
        Args:
            task_id: タスクID
            
        Returns:
            タスク用ワークスペースのパス
        """
        task_workspace = self.workspace_dir / f"task_{task_id}"
        
        # 既存のワークスペースがあれば削除
        if task_workspace.exists():
            shutil.rmtree(task_workspace)
            
        # 共有ワークスペースが存在すればコピー
        if self.shared_workspace.exists():
            shutil.copytree(self.shared_workspace, task_workspace)
            logger.info(f"Copied shared workspace to {task_workspace}")
        else:
            # 共有ワークスペースがなければ空のディレクトリを作成
            task_workspace.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created empty workspace at {task_workspace}")
            
        # プロジェクト直下の.claudeディレクトリがあればコピー
        project_claude_dir = Path.cwd() / ".claude"
        if project_claude_dir.exists():
            task_claude_dir = task_workspace / ".claude"
            if task_claude_dir.exists():
                shutil.rmtree(task_claude_dir)
            shutil.copytree(project_claude_dir, task_claude_dir)
            logger.info(f"Copied .claude directory from project root to {task_workspace}")
        else:
            # .claude/settings.jsonを作成してWriteツールを許可
            claude_dir = task_workspace / ".claude"
            claude_dir.mkdir(exist_ok=True)
            
            settings_content = {
                "permissions": {
                    "allow": [
                        "Write"
                    ]
                }
            }
            
            settings_file = claude_dir / "settings.json"
            settings_file.write_text(json.dumps(settings_content, indent=2))
            logger.info(f"Created {settings_file} with Write permission")
            
        # スナップショットを記録
        self.task_snapshots[task_id] = self._create_snapshot(task_workspace)
        
        # ベースファイルを保存
        self._save_base_files(task_id, task_workspace)
        
        return task_workspace
    
    def _detect_changes(self, base_snapshot: Dict[str, FileMetadata], 
                       current_snapshot: Dict[str, FileMetadata]) -> Dict[str, List[str]]:
        """2つのスナップショット間の差分を検出
        
        Args:
            base_snapshot: 基準となるスナップショット
            current_snapshot: 現在のスナップショット
            
        Returns:
            変更の種類別ファイルリスト
        """
        base_files = set(base_snapshot.keys())
        current_files = set(current_snapshot.keys())
        
        changes = {
            "new": list(current_files - base_files),
            "deleted": list(base_files - current_files),
            "modified": []
        }
        
        # 変更されたファイルを検出
        for filepath in base_files & current_files:
            if base_snapshot[filepath].hash != current_snapshot[filepath].hash:
                changes["modified"].append(filepath)
                
        return changes
    
    async def integrate_task_results(self, task_id: str, task_workspace: Path,
                                   conflict_resolver: Optional['ConflictResolver'] = None) -> Dict[str, int]:
        """タスク結果を共有ワークスペースに統合
        
        Args:
            task_id: タスクID
            task_workspace: タスクのワークスペース
            conflict_resolver: 競合解決に使用するリゾルバー
            
        Returns:
            統合結果のサマリー（new, modified, conflictの数）
        """
        # 現在のスナップショットを作成
        base_snapshot = self.task_snapshots.get(task_id, {})
        task_snapshot = self._create_snapshot(task_workspace)
        shared_snapshot = self._create_snapshot(self.shared_workspace)
        
        # 変更を検出
        changes = self._detect_changes(base_snapshot, task_snapshot)
        
        result = {
            "new": 0,
            "modified": 0, 
            "conflict": 0,
            "deleted": 0
        }
        
        # 共有ワークスペースが存在しない場合は作成
        self.shared_workspace.mkdir(parents=True, exist_ok=True)
        
        # 新規ファイルの処理
        for filepath in changes["new"]:
            src_file = task_workspace / filepath
            dst_file = self.shared_workspace / filepath
            
            # ディレクトリを作成
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            
            # ファイルをコピー
            shutil.copy2(src_file, dst_file)
            logger.info(f"Added new file: {filepath}")
            result["new"] += 1
            
        # 変更されたファイルの処理
        for filepath in changes["modified"]:
            src_file = task_workspace / filepath
            dst_file = self.shared_workspace / filepath
            
            # 共有側も変更されているかチェック
            if filepath in shared_snapshot:
                if filepath not in base_snapshot or \
                   shared_snapshot[filepath].hash != base_snapshot[filepath].hash:
                    # 3-wayマージが必要
                    if conflict_resolver:
                        logger.info(f"Attempting 3-way merge for {filepath}")
                        
                        # ベースファイルを取得
                        base_file = None
                        if filepath in base_snapshot:
                            base_file = self._get_base_file(task_id, filepath)
                            if base_file:
                                logger.debug(f"Found base file for {filepath}")
                            
                        # 3-wayマージを実行
                        resolution = await conflict_resolver.resolve_three_way_conflict(
                            base_file=base_file,
                            shared_file=dst_file,
                            task_file=src_file,
                            task_id=task_id,
                            artifact_manager=self
                        )
                        
                        if resolution.strategy == "merged" and resolution.merged_file_path:
                            shutil.copy2(resolution.merged_file_path, dst_file)
                            logger.info(f"Successfully merged {filepath}")
                            result["modified"] += 1
                        else:
                            # マージ失敗 - バージョンサフィックス付与
                            versioned_name = f"{dst_file.stem}_{task_id}{dst_file.suffix}"
                            versioned_path = dst_file.parent / versioned_name
                            shutil.copy2(src_file, versioned_path)
                            logger.warning(f"Merge failed for {filepath}, saved as {versioned_name}")
                            result["conflict"] += 1
                    else:
                        # ConflictResolverがない場合はバージョンサフィックス付与
                        versioned_name = f"{dst_file.stem}_{task_id}{dst_file.suffix}"
                        versioned_path = dst_file.parent / versioned_name
                        shutil.copy2(src_file, versioned_path)
                        logger.warning(f"Conflict detected for {filepath}, saved as {versioned_name}")
                        result["conflict"] += 1
                else:
                    # 共有側は変更されていない - 単純に上書き
                    shutil.copy2(src_file, dst_file)
                    logger.info(f"Updated file: {filepath}")
                    result["modified"] += 1
            else:
                # 共有側に存在しない（削除された？） - 新規として追加
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                logger.info(f"Re-added file: {filepath}")
                result["new"] += 1
                
        # 削除されたファイルの処理（現在は記録のみ）
        for filepath in changes["deleted"]:
            logger.info(f"File deleted in task: {filepath}")
            result["deleted"] += 1
            
        logger.info(f"Integration complete for task {task_id}: "
                   f"{result['new']} new, {result['modified']} modified, "
                   f"{result['conflict']} conflicts, {result['deleted']} deleted")
        
        return result