"""STDIO-only search/fetch launcher; the operator's token never enters client config."""
from __future__ import annotations
from contextledger.paths import PROJECT_ROOT

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys


def load_token(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("credential file must not be a symlink")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 4096):
            raise ValueError("credential file must be owned and private")
        value = json.load(handle)
    token = value.get("token") if isinstance(value, dict) else None
    if not isinstance(token, str) or not re.fullmatch(r"clt_[0-9a-f]{32}\.[A-Za-z0-9_-]{30,100}", token):
        raise ValueError("invalid credential file")
    return token


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:17864")
    parser.add_argument("--corpus", default="orgforge")
    args = parser.parse_args(argv)
    try:
        token = load_token(args.credentials)
    except (OSError, ValueError):
        print("ContextLedger private credential is unavailable; contact the operator.", file=sys.stderr)
        return 1
    # No platform credentials, paid internal answers, or compliance tool are forwarded.
    os.environ.update(CL_TOOL_TOKEN=token, CL_TOOL_URL=args.url,
                      CL_TOOL_CORPUS=args.corpus, CL_MCP_ENABLE_ASK="false", CL_MCP_ENABLE_AUDIT="false")
    from contextledger.interfaces.mcp_server import main as run_server
    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
