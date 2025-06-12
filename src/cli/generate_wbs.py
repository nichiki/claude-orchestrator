"""
WBS生成用のCLIコマンド
"""
import asyncio
import logging
from pathlib import Path
import typer
from typing import Optional

from src.core.wbs_generator import WBSGenerator

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = typer.Typer(help="WBS (Work Breakdown Structure) Generator")


@app.command()
def main(
    requirement: str,
    output: Optional[Path] = typer.Option(
        None, 
        "-o", 
        "--output",
        help="出力ファイルパス (デフォルト: ./project.yaml)"
    ),
    workspace: Path = typer.Option(
        "./wbs_workspace",
        "--workspace",
        help="作業ディレクトリ"
    ),
    cleanup: bool = typer.Option(
        True,
        "--cleanup/--no-cleanup",
        help="実行後に作業ディレクトリを削除"
    )
):
    """要求文からWBSを生成"""
    
    # デフォルトの出力先
    if output is None:
        output = Path("./project.yaml")
    
    try:
        # WBSGeneratorを初期化
        generator = WBSGenerator(workspace_dir=str(workspace))
        
        # 非同期関数を実行
        result_path = asyncio.run(generator.generate(requirement, output))
        
        typer.echo(f"✨ WBS generated successfully: {result_path}")
        
        # プレビューを表示
        if result_path.exists():
            typer.echo("\n--- Preview ---")
            with open(result_path, 'r') as f:
                lines = f.readlines()[:20]  # 最初の20行
                for line in lines:
                    typer.echo(line.rstrip())
                if len(f.readlines()) > 20:
                    typer.echo("... (truncated)")
        
        # クリーンアップ
        if cleanup:
            generator.cleanup()
            
    except Exception as e:
        typer.echo(f"❌ Error: {str(e)}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()