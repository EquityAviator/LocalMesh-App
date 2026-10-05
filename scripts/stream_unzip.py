#!/usr/bin/env python3
"""Stream-extract a remote ZIP over HTTP Range requests (no local copy).

Used to install the Android NDK into this disk-constrained sandbox without
ever storing the 600 MB zip. Stdlib only: urllib + zipfile.

Usage: python3 stream_unzip.py <url> <dest_dir> [exclude_substring ...]
"""
import io
import os
import sys
import time
import urllib.request
import zipfile


class HTTPRangeFile(io.RawIOBase):
    """Minimal seekable read-only file over HTTP Range requests."""

    def __init__(self, url: str, chunk: int = 1 << 20) -> None:
        self.url = url
        self.chunk = chunk
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
        self.pos = 0
        self._buf = b""
        self._buf_start = 0
        self._fetched = 0  # bytes pulled from network (progress reporting)

    def _fill(self, start: int, end: int) -> None:
        a = (start // self.chunk) * self.chunk
        b = min(self.size, max(end, a + self.chunk))
        if self._buf and a == self._buf_start and b <= self._buf_start + len(self._buf):
            return
        last: Exception | None = None
        for attempt in range(5):
            try:
                req = urllib.request.Request(
                    self.url, headers={"Range": f"bytes={a}-{b - 1}"}
                )
                with urllib.request.urlopen(req, timeout=120) as r:
                    self._buf = r.read()
                self._buf_start = a
                self._fetched += len(self._buf)
                return
            except Exception as exc:  # noqa: BLE001 — retry any transport error
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise last if last else RuntimeError("range fetch failed")

    def read(self, n: int = -1) -> bytes:  # type: ignore[override]
        if n == -1:
            n = self.size - self.pos
        end = min(self.size, self.pos + n)
        if end <= self.pos:
            return b""
        self._fill(self.pos, end)
        off = self.pos - self._buf_start
        out = self._buf[off : off + (end - self.pos)]
        self.pos += len(out)
        return out

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        elif whence == 2:
            self.pos = self.size + offset
        return self.pos

    def tell(self) -> int:
        return self.pos

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True


def main() -> int:
    url, dest = sys.argv[1], sys.argv[2]
    excludes = sys.argv[3:]
    os.makedirs(dest, exist_ok=True)
    f = HTTPRangeFile(url)
    print(f"remote size: {f.size / 1e6:.0f} MB", flush=True)
    zf = zipfile.ZipFile(f)  # reads the central directory via range requests
    names = zf.namelist()
    root = names[0].split("/")[0] if "/" in names[0] else ""
    kept = 0
    started = time.time()
    for idx, info in enumerate(zf.infolist()):
        name = info.filename
        if info.is_dir():
            continue
        rel = name[len(root) + 1 :] if root and name.startswith(root + "/") else name
        if any(x in ("/" + rel) for x in excludes):
            continue
        target = os.path.join(dest, rel)
        if not os.path.abspath(target).startswith(os.path.abspath(dest)):
            continue  # zip-slip guard
        if os.path.exists(target) and os.path.getsize(target) == info.file_size:
            continue  # resume: already extracted in a previous attempt
        os.makedirs(os.path.dirname(target), exist_ok=True)
        last: Exception | None = None
        for attempt in range(5):
            try:
                src = zf.open(info)
                with open(target, "wb") as out:
                    while True:
                        data = src.read(1 << 20)
                        if not data:
                            break
                        out.write(data)
                last = None
                break
            except Exception:  # noqa: BLE001 — retry per-file on transport errors
                last = Exception(f"file {rel} attempt {attempt + 1}")
                time.sleep(1.5 * (attempt + 1))
        if last is not None:
            raise last
        mode = info.external_attr >> 16
        if mode:
            os.chmod(target, mode)
        kept += 1
        if kept % 1000 == 0:
            print(f"  {kept} files, {idx}/{len(names)}, {time.time() - started:.0f}s", flush=True)
    print(f"done: {kept} files extracted in {time.time() - started:.0f}s "
          f"(network {f._fetched / 1e6:.0f} MB touched)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
