"""
WBS (Work Breakdown Structure) を自動生成する
Claude Codeを使って要求文からproject.yamlを生成
"""
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from .task_executor import TaskExecutor

logger = logging.getLogger(__name__)


class WBSGenerator:
    """要求文からWBSを自動生成"""
    
    def __init__(self, workspace_dir: str = "./wbs_workspace"):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(exist_ok=True)
        
        # WBS生成用のTaskExecutor
        self.executor = TaskExecutor(
            workspace_dir=str(self.workspace_dir),
            timeout=300  # 5分
        )
    
    async def generate(
        self, 
        requirement: str,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        要求文からWBSを生成
        
        Args:
            requirement: プロジェクトの要求文
            output_path: 出力先のパス（指定しない場合は自動生成）
            
        Returns:
            生成されたYAMLファイルのパス
        """
        
        # タスクIDを生成
        task_id = f"wbs_{int(datetime.now().timestamp())}"
        
        # プロンプトを作成
        prompt = self._create_prompt(requirement)
        
        logger.info(f"Generating WBS for requirement: {requirement[:50]}...")
        
        # Claude Codeで生成
        result = await self.executor.execute({
            "id": task_id,
            "name": "Generate WBS",
            "prompt": prompt
        })
        
        if not result.success:
            raise RuntimeError(f"WBS generation failed: {result.error}")
        
        # 生成されたファイルを確認
        generated_file = self.workspace_dir / task_id / "project.yaml"
        
        if not generated_file.exists():
            # project.yamlが見つからない場合、他のYAMLファイルを探す
            yaml_files = list((self.workspace_dir / task_id).glob("*.yaml"))
            if yaml_files:
                generated_file = yaml_files[0]
                logger.warning(f"Expected project.yaml but found {generated_file.name}")
            else:
                raise RuntimeError("No YAML file was generated")
        
        # 指定された場所にコピー
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            import shutil
            shutil.copy2(generated_file, output_path)
            logger.info(f"WBS saved to: {output_path}")
            return output_path
        else:
            # 出力先が指定されていない場合は生成されたファイルのパスを返す
            return generated_file
    
    def _create_prompt(self, requirement: str) -> str:
        """WBS生成用のプロンプトを作成"""
        return f"""あなたはプロジェクト管理の専門家です。
以下の要求に基づいて、WBS (Work Breakdown Structure) をYAML形式で生成してください。

要求: {requirement}

生成するWBSは以下の形式に従ってください：

```yaml
name: "プロジェクト名"
description: "プロジェクトの説明"
phases:
  - id: "phase-id"
    name: "フェーズ名"
    tasks:
      - id: "task-id"
        name: "タスク名"
        prompt: "このタスクで実行する具体的な指示"
        dependencies: []  # 依存するタスクのIDリスト
```

重要な点：
1. フェーズは論理的な単位で分割（例：設計、実装、テスト）
2. タスクは1つの明確な成果物を生成する単位
3. 依存関係は必要最小限に（並列実行を活かすため）
4. 各タスクのpromptは具体的で実行可能な指示
5. タスクIDとフェーズIDは分かりやすく一意に

生成したYAMLは project.yaml という名前で保存してください。
"""
    
    def cleanup(self):
        """作業ディレクトリをクリーンアップ"""
        import shutil
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir)
            logger.info("Cleaned up WBS workspace")