# コンフリクト解決設計

## 1. ファイル名の競合防止

### タスク定義での明示的な出力パス指定
```yaml
tasks:
  - id: "service-a"
    outputs:
      - path: "services/service_a/config.py"
        type: "python"
  - id: "service-b"
    outputs:
      - path: "services/service_b/config.py"
        type: "python"
```

### 名前空間の自動付与
```python
def get_output_path(task_id: str, filename: str) -> str:
    # task_idを名前空間として使用
    return f"{task_id}/{filename}"
```

## 2. 共有リソースのロック機構

```python
class ResourceLock:
    def __init__(self):
        self.locks = {}
    
    async def acquire(self, resource_name: str, task_id: str):
        """リソースのロックを取得"""
        if resource_name in self.locks:
            await self.locks[resource_name].wait()
        self.locks[resource_name] = asyncio.Lock()
        await self.locks[resource_name].acquire()
    
    def release(self, resource_name: str):
        """リソースのロックを解放"""
        if resource_name in self.locks:
            self.locks[resource_name].release()
```

## 3. マージ戦略

### 自動マージ可能なファイルタイプ
- **requirements.txt**: 行の追加
- **__init__.py**: インポートの追加
- **config.json**: キーのマージ

### マージ例
```python
def merge_requirements(file1: str, file2: str) -> str:
    """requirements.txtをマージ"""
    deps1 = set(file1.strip().split('\n'))
    deps2 = set(file2.strip().split('\n'))
    merged = sorted(deps1.union(deps2))
    return '\n'.join(merged)
```

## 4. コンフリクト検出と通知

```python
class ConflictDetector:
    def detect_conflicts(self, artifacts: List[Artifact]) -> List[Conflict]:
        """成果物間のコンフリクトを検出"""
        conflicts = []
        file_map = {}
        
        for artifact in artifacts:
            if artifact.path in file_map:
                conflicts.append(Conflict(
                    path=artifact.path,
                    task1=file_map[artifact.path].task_id,
                    task2=artifact.task_id,
                    type=ConflictType.FILE_OVERWRITE
                ))
            file_map[artifact.path] = artifact
        
        return conflicts
```

## 5. 解決戦略の選択

```yaml
conflict_resolution:
  strategy: "manual"  # manual, auto-merge, fail-fast, last-wins
  rules:
    - pattern: "*.txt"
      strategy: "auto-merge"
    - pattern: "config/*"
      strategy: "manual"
    - pattern: "*.py"
      strategy: "fail-fast"
```

## 6. Human-in-the-loopでの解決

```python
async def resolve_conflict_with_human(conflict: Conflict):
    """人間による競合解決"""
    notification = f"""
    競合が検出されました:
    - ファイル: {conflict.path}
    - タスク1: {conflict.task1} 
    - タスク2: {conflict.task2}
    
    解決方法を選択してください:
    1. タスク1のファイルを使用
    2. タスク2のファイルを使用
    3. 手動でマージ
    4. 両方保持（別名で保存）
    """
    
    # 通知を送信して人間の判断を待つ
    resolution = await human_interface.request_resolution(notification)
    return resolution
```