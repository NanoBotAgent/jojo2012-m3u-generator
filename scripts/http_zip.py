"""
Read a remote ZIP over HTTP range requests as a seekable file object, so a
6 GB archive can be inspected and individual members extracted without ever
storing the whole archive on disk.

Only the byte ranges actually read are fetched. Works with zip64 archives
that Info-ZIP's `unzip` struggles with.
"""
import io
import os
import urllib.request

UA = "Mozilla/5.0"
CHUNK = 8 << 20
MAX_BULK_READ = 64 << 20


class HttpFile(io.RawIOBase):
    """Minimal seekable read-only file over HTTP Range requests."""

    def __init__(self, url, size=None, timeout=300):
        self.url = url
        self.pos = 0
        self.timeout = timeout
        if size is None:
            req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
            with urllib.request.urlopen(req, timeout=60) as r:
                size = int(r.headers.get("Content-Length", 0))
        self.size = size

    def seekable(self):
        return True

    def readable(self):
        return True

    def writable(self):
        return False

    def tell(self):
        return self.pos

    def seek(self, offset, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            self.pos = offset
        elif whence == os.SEEK_CUR:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def _fetch(self, start, length):
        end = min(start + length - 1, self.size - 1)
        if start > end:
            return b""
        req = urllib.request.Request(
            self.url,
            headers={"User-Agent": UA, "Range": "bytes=%d-%d" % (start, end)},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read()

    def read(self, size=-1):
        if size is None or size < 0:
            size = self.size - self.pos
            if size > MAX_BULK_READ:
                raise ValueError(
                    "refusing to read %d bytes in one call; the archive is "
                    "6.7 GB and must be streamed member by member" % size
                )
        if size == 0:
            return b""
        parts = []
        remaining = size
        while remaining > 0:
            block = self._fetch(self.pos, min(remaining, CHUNK))
            if not block:
                break
            parts.append(block)
            self.pos += len(block)
            remaining -= len(block)
        return b"".join(parts)

    def readinto(self, b):
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def open_remote_zip(url, size=None):
    """Return (zipfile.ZipFile, HttpFile). Caller owns both."""
    import zipfile

    hf = HttpFile(url, size=size)
    return zipfile.ZipFile(hf, "r"), hf
