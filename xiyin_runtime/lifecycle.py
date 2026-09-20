"""One foreground owner per data root. File remains; the OS releases the lock."""
import os
from pathlib import Path


class RuntimeLease:
    def __init__(self, path: Path):
        self._file = Path(path).open("a+b")
        try:
            if os.fstat(self._file.fileno()).st_size == 0:
                self._file.write(b"0")
                self._file.flush()
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._file.close()
            raise RuntimeError("Another XIYIN runtime owns this data root") from exc

    def close(self):
        if not self._file.closed:
            try:
                self._file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
