"""Durable emergency inhibition, shared by the signer and root recovery client."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat

from .custody import CustodyError


def directory(path, owner_uid=0):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise CustodyError('Recovery paths must be absolute and without symlinks')
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o022:
        raise CustodyError('Recovery directory ownership or permissions are unsafe')


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Inhibit:
    def __init__(self, path, owner_uid=0):
        self.path = Path(path)
        self.owner_uid = owner_uid

    def active(self):
        # An inaccessible/missing control directory is an error, not an enable.
        directory(self.path.parent, self.owner_uid)
        try:
            self.path.lstat()
            return True  # Any entry, including a malformed one, inhibits signing.
        except FileNotFoundError:
            return False

    def disable(self):
        directory(self.path.parent, self.owner_uid)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
                raise CustodyError('Unsafe emergency control file')
            os.fsync(fd)
        finally:
            os.close(fd)
        sync_directory(self.path.parent)

    def resume(self):
        directory(self.path.parent, self.owner_uid)
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
            raise CustodyError('Unsafe emergency control file')
        self.path.unlink()
        sync_directory(self.path.parent)


@contextmanager
def control_lock(path, owner_uid=0):
    path = Path(path)
    directory(path.parent, owner_uid)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o077:
            raise CustodyError('Unsafe recovery control lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
