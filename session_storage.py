"""Bounded local evidence storage. Only managed session folders are pruned."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import shutil
import threading
import os
from datetime import datetime, timezone
import time

MAX_SESSIONS = 10
MAX_BYTES = 90_000_000
_lock = threading.RLock()


def active(directory):
    marker=directory/'.active'
    if not marker.exists():return False
    try:
        pid=int(marker.read_text())
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=kernel.OpenProcess(0x00100000,False,pid)
            if not handle:return ctypes.get_last_error()==5
            try:return kernel.WaitForSingleObject(handle,0)==258
            finally:kernel.CloseHandle(handle)
        os.kill(pid,0)
        return True
    except (ValueError,OSError):return False


def prune(root, current=None, max_sessions=MAX_SESSIONS, max_bytes=MAX_BYTES):
    root=Path(root).resolve()
    if not root.exists():return []
    current=Path(current).resolve() if current else None
    removed=[]
    with _lock:
        # No traversal through junctions/symlinks. Only folders we explicitly manage.
        folders=[p for p in root.iterdir() if p.is_dir() and not p.is_symlink()
                 and p.resolve().parent==root and (p/'session.json').is_file()]
        folders.sort(key=lambda p:p.stat().st_mtime,reverse=True)
        def size(p):
            return sum(f.stat().st_size for f in p.rglob('*') if f.is_file() and not f.is_symlink())
        sizes={p:size(p) for p in folders}
        # Never delete the currently writing session. Other active owners are pinned.
        candidates=[p for p in reversed(folders) if p.resolve()!=current and not active(p)]
        total=sum(sizes.values());count=len(folders)
        for folder in candidates:
            if count<=max_sessions and total<=max_bytes:break
            resolved=folder.resolve()
            if resolved.parent!=root:raise ValueError('Refusing deletion outside session root')
            shutil.rmtree(resolved)
            total-=sizes[folder];count-=1;removed.append(folder.name)
        if removed:
            # Bounded summary, not an ever-growing deletion log.
            (root/'retention.json').write_text(json.dumps(dict(removed=removed,remaining_bytes=total,
                remaining_sessions=count,max_bytes=max_bytes,max_sessions=max_sessions)),encoding='utf-8')
    return removed


def register(directory, kind):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'session.json').write_text(json.dumps(dict(kind=kind,retention='latest 10; 90 MB; active sessions protected')),encoding='utf-8')
    (directory/'.active').write_text(str(os.getpid()))
    # Reserve space for the new active log and report before they grow.
    prune(directory.parent,directory,max_bytes=75_000_000)


def finish(directory):
    if directory:
        directory=Path(directory)
        (directory/'.active').unlink(missing_ok=True)
        prune(directory.parent,directory)


class SessionHandler(RotatingFileHandler):
    def __init__(self,path):
        super().__init__(path,maxBytes=4_000_000,backupCount=1,encoding='utf-8')

    def doRollover(self):
        super().doRollover()
        directory=Path(self.baseFilename).parent
        prune(directory.parent,directory,max_bytes=75_000_000)


class EventLog:
    def __init__(self,path):
        self.logger=logging.Logger('session-'+str(path))
        self.handler=SessionHandler(path)
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(self.handler)

    def __enter__(self):return self.write

    def write(self,event,**data):
        self.logger.info(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),
            monotonic_s=time.monotonic(),event=event,**data),allow_nan=False))

    def __exit__(self,*args):self.handler.close()
