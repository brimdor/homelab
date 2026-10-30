"""Copy one projected TLS generation into new private regular files; never log keys."""
import os
from pathlib import Path
import stat


def stage(source, destination):
    parent = Path(destination).parent
    for path in [parent, *parent.parents]:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("Identity output requires existing non-symlink parents")
    # Pin the Kubernetes atomic writer generation before opening either file.
    generation = os.open(Path(source) / "..data", os.O_RDONLY | os.O_DIRECTORY)
    values = {}
    try:
        for name in ["tls.crt", "tls.key"]:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=generation)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1024 * 1024:
                    raise ValueError("Invalid projected TLS input")
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    values[name] = stream.read(1024 * 1024 + 1)
                if len(values[name]) != info.st_size:
                    raise ValueError("Projected TLS input changed")
            finally:
                os.close(fd)
    finally:
        os.close(generation)
    # Refuse existing output, including dangling symlinks; no key overwrite.
    os.mkdir(destination, 0o700)
    try:
        for name, value in values.items():
            fd = os.open(Path(destination) / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for name in values:
            (Path(destination) / name).unlink(missing_ok=True)
        os.rmdir(destination)
        raise


if __name__ == "__main__":
    stage("/projected-tls", "/run/tsurreal/identity")
