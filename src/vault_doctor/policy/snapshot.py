"""文件快照：修复落盘前按会话复制受影响文件，支持一键回滚。

设计取舍：不做 git/影子仓库双轨——快照的唯一职责是回滚本工具自己的
写入，按会话复制将被修改的文件即可，git 与非 git 库统一、零外部依赖。
copy2 保留 mtime/size，回滚后增量索引指纹自动吻合。
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_SESSION_ID_RE = re.compile(r"[A-Za-z0-9\-]+")


class SnapshotError(RuntimeError):
    pass


@dataclass
class Snapshot:
    session_id: str
    vault: Path
    dir: Path
    files: list[str]


def snapshots_root(vault: Path) -> Path:
    return vault / ".vaultdoctor" / "snapshots"


def create_snapshot(vault: Path, files: list[str]) -> Snapshot:
    """把 vault 内的指定文件复制进 .vaultdoctor/snapshots/<session>/，返回快照。"""
    session_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    snap_dir = snapshots_root(vault) / session_id
    stored: list[str] = []
    for relpath in sorted(set(files)):
        src = vault / relpath
        dst = snap_dir / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        stored.append(relpath)
    manifest = {
        "session_id": session_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": stored,
    }
    (snap_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return Snapshot(session_id=session_id, vault=vault, dir=snap_dir, files=stored)


def list_snapshots(vault: Path) -> list[str]:
    root = snapshots_root(vault)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "manifest.json").is_file()
    )


def list_snapshots_detail(vault: Path) -> list[dict]:
    """快照详情（旧→新）：session_id、创建时间、修改文件清单——回答"这份快照改了什么"。"""
    detail: list[dict] = []
    for sid in list_snapshots(vault):
        manifest_path = snapshots_root(vault) / sid / "manifest.json"
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        detail.append(
            {
                "session_id": sid,
                "created_at": data.get("created_at", ""),
                "files": data.get("files", []),
            }
        )
    return detail


def rollback(vault: Path, session_id: str) -> list[str]:
    """把一次会话快照复制回原位，返回恢复的文件列表。"""
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise SnapshotError(f"非法 session id：{session_id!r}")
    snap_dir = snapshots_root(vault) / session_id
    manifest_path = snap_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SnapshotError(f"未找到快照 {session_id}（用 vault-doctor snapshots 查看）")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored: list[str] = []
    for relpath in manifest["files"]:
        src = snap_dir / relpath
        dst = vault / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        restored.append(relpath)
    return restored
