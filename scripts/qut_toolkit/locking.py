"""Nonblocking advisory output-root lock. All writers must cooperate.

Keep the lock file permanently: unlinking it can split contenders across inodes.
No PID/age heuristics or stale-lock stealing; the OS releases locks on process exit.
Use local filesystems with OS locking semantics, not unverified network shares.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat

LOCK_NAME = '.qut-writer.lock'


class WriterLockError(RuntimeError):
    """Output root is already locked, or an exclusive lock cannot be established."""


def _is_link(path):
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def checked_root(root):
    """Create a root only after rejecting linked roots and linked ancestors."""
    root = Path(os.path.abspath(root))
    for part in (*reversed(root.parents), root):
        if _is_link(part):
            raise ValueError('Links/junctions are not allowed in output roots')
    root.mkdir(parents=True, exist_ok=True)
    for part in (*reversed(root.parents), root):
        if _is_link(part):
            raise ValueError('Links/junctions are not allowed in output roots')
    return root.resolve()


@contextmanager
def writer_lock(root):
    """Yield the canonical root under a nonblocking exclusive OS-backed lock.

    Acquire BEFORE constructing Store/reading checkpoints, hold through final save.
    Raises WriterLockError immediately on contention; ValueError for linked paths.
    The persistent lock file is not an indication that the root is currently busy.
    """
    root = checked_root(root)
    path = root / LOCK_NAME
    if _is_link(path):
        raise ValueError('Linked writer lock is not allowed')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags, 0o600)
    locked = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _is_link(path):
            raise ValueError('Writer lock must be an unlinked regular file')
        if not os.path.samestat(info, path.stat()):
            raise WriterLockError('Writer lock changed while opening')
        try:
            if os.name == 'nt':
                import msvcrt
                # Windows permits locking a byte past EOF: lock before initializing
                # so concurrent first-open contenders cannot modify the locked byte.
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise WriterLockError('Output root is busy or exclusive locking is unavailable') from exc
        if info.st_size == 0:
            os.write(fd, b'\0')
        yield root
    finally:
        try:
            if locked:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
