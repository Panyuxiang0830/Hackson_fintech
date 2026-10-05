"""Read selected archive members through bounded HTTP Range requests."""

from __future__ import annotations

import io
from collections import OrderedDict

import requests


class RemoteZipReader(io.RawIOBase):
    def __init__(self, url: str, size: int, block_size: int = 1024 * 1024):
        super().__init__()
        self.url = url
        self.size = size
        self.block_size = block_size
        self.position = 0
        self.downloaded = 0
        self.session = requests.Session()
        self.cache: OrderedDict[int, bytes] = OrderedDict()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        target = offset if whence == io.SEEK_SET else self.position + offset if whence == io.SEEK_CUR else self.size + offset
        if target < 0:
            raise ValueError("negative seek")
        self.position = target
        return target

    def read(self, size: int = -1) -> bytes:
        stop = self.size if size < 0 else min(self.size, self.position + size)
        parts = []
        while self.position < stop:
            block = self.position // self.block_size
            if block not in self.cache:
                start = block * self.block_size
                end = min(self.size, start + self.block_size) - 1
                with self.session.get(self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=(15, 90), stream=True) as response:
                    expected = f"bytes {start}-{end}/{self.size}"
                    if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                        raise RuntimeError("archive server did not honor the requested byte range")
                    payload = response.content
                    if len(payload) != end - start + 1:
                        raise RuntimeError("incomplete archive byte range")
                self.downloaded += len(payload)
                self.cache[block] = payload
                while len(self.cache) > 4:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(block)
            offset = self.position % self.block_size
            count = min(stop - self.position, len(self.cache[block]) - offset)
            parts.append(self.cache[block][offset : offset + count])
            self.position += count
        return b"".join(parts)

    def close(self) -> None:
        self.session.close()
        super().close()
