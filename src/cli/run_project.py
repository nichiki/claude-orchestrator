#!/usr/bin/env python3
"""
プロジェクト実行用CLIスクリプト
"""
import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from src.core import Orchestrator


app = typer.Typer()
console = Console()


def setup_logging(verbose: bool = False):
    """ロギングの設定"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('orchestrator.log'),
            logging.StreamHandler(sys.stdout) if verbose else logging.NullHandler()
        ]
    )


def create_progress_callback(progress: Progress, task_id):
    """進捗表示用のコールバックを作成"""
    task_status = {}
    
    def callback(update):
        update_type = update["type"]
        
        if update_type == "project_started":
            summary = update["summary"]
            progress.update(task_id, total=summary["total"])
            
        elif update_type == "task_started":
            task_status[update["task_id"]] = "🔄 実行中"
            console.print(f"[yellow]▶ タスク開始:[/yellow] {update['task_name']}")
            
        elif update_type == "task_completed":
            task_status[update["task_id"]] = "✅ 完了"
            console.print(f"[green]✓ タスク完了:[/green] {update['task_id']}")
            
        elif update_type == "task_failed":
            task_status[update["task_id"]] = "❌ 失敗"
            console.print(f"[red]✗ タスク失敗:[/red] {update['task_id']} - {update['error']}")
            
        elif update_type == "progress_update":
            summary = update["summary"]
            completed = summary["completed"] + summary["failed"]
            progress.update(task_id, completed=completed)
            
    return callback


@app.command()
def run(
    wbs_path: Path = typer.Argument(..., help="WBSファイルのパス"),
    workspace: Path = typer.Option("./workspace", help="作業ディレクトリ"),
    state_file: Path = typer.Option(None, help="状態ファイルのパス（中断からの再開用）"),
    dry_run: bool = typer.Option(False, help="ドライラン（実際の実行はしない）"),
    max_concurrent: int = typer.Option(3, help="最大並列実行数"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="詳細ログを表示"),
):
    """プロジェクトを実行する"""
    setup_logging(verbose)
    
    # ヘッダー表示
    console.print(Panel.fit(
        f"🚀 [bold blue]AI駆動プロジェクト実行システム[/bold blue]\n"
        f"📄 WBS: {wbs_path}\n"
        f"📁 Workspace: {workspace}\n"
        f"{'🔧 Mode: DRY RUN' if dry_run else '⚡ Mode: 実行'}",
        title="プロジェクト実行開始"
    ))
    
    # Orchestratorの設定
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        
        task_id = progress.add_task("プロジェクト実行中...", total=100)
        
        orchestrator = Orchestrator(
            wbs_path=str(wbs_path),
            workspace_dir=str(workspace),
            state_file=str(state_file) if state_file else None,
            max_concurrent=max_concurrent,
            dry_run=dry_run,
            progress_callback=create_progress_callback(progress, task_id)
        )
        
        # 実行
        try:
            results = asyncio.run(orchestrator.run())
            
            # 結果のサマリーを表示
            display_results(results, orchestrator.get_status_report())
            
        except Exception as e:
            console.print(f"[red]エラーが発生しました: {e}[/red]")
            raise typer.Exit(1)


def display_results(results, status_report):
    """実行結果を表示"""
    console.print("\n")
    
    # サマリーテーブル
    summary = status_report["summary"]
    table = Table(title="実行結果サマリー")
    table.add_column("項目", style="cyan")
    table.add_column("値", style="white")
    
    table.add_row("総タスク数", str(summary["total"]))
    table.add_row("完了", f"[green]{summary['completed']}[/green]")
    table.add_row("実行中", f"[yellow]{summary['in_progress']}[/yellow]")
    table.add_row("失敗", f"[red]{summary['failed']}[/red]")
    table.add_row("未実行", str(summary["pending"]))
    
    console.print(table)
    
    # 失敗タスクの詳細
    failed_tasks = [t for t in status_report["tasks"] if t["status"] == "failed"]
    if failed_tasks:
        console.print("\n[red]失敗したタスク:[/red]")
        for task in failed_tasks:
            console.print(f"  - {task['id']}: {task['name']}")
            if task.get("error"):
                console.print(f"    エラー: {task['error']}")
    
    # 成功メッセージ
    if summary["failed"] == 0 and summary["pending"] == 0:
        console.print("\n[green]✨ プロジェクトが正常に完了しました！[/green]")
    elif summary["failed"] > 0:
        console.print("\n[red]⚠️  一部のタスクが失敗しました。[/red]")
    else:
        console.print("\n[yellow]⚠️  一部のタスクが未実行です。[/yellow]")


@app.command()
def status(
    wbs_path: Path = typer.Argument(..., help="WBSファイルのパス"),
    state_file: Path = typer.Argument(..., help="状態ファイルのパス"),
    workspace: Path = typer.Option("./workspace", help="作業ディレクトリ"),
):
    """プロジェクトの状態を確認する"""
    orchestrator = Orchestrator(
        wbs_path=str(wbs_path),
        workspace_dir=str(workspace),
        state_file=str(state_file),
        dry_run=True
    )
    
    report = orchestrator.get_status_report()
    display_results([], report)


if __name__ == "__main__":
    app()