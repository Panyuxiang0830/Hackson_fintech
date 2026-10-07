"""Sync ONLY approved model/demo configuration over SSH stdin, never print keys.

The configuration is a runtime artifact outside the checkout, written atomically
with mode 0600. Auth0, other credentials, and the local APP_SECRET_KEY are excluded.
"""

import argparse
import json
from pathlib import Path
import shlex
import subprocess
from urllib.parse import urlparse

from dotenv import dotenv_values


def preview_config(values, public_url, security_dir, qdrant_url, hf_home=None):
    if urlparse(public_url).hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Preview URL must be loopback")
    if not Path(security_dir).is_absolute():
        raise ValueError("Use an absolute, isolated demo security directory")
    key = (values.get("LLM_API_KEY") or "").strip()
    if not key or "\n" in key or "\r" in key or "\x00" in key:
        raise ValueError("A nonempty single-line model key is required in the local ignored config")
    config = {
        "APP_PUBLIC_URL": public_url, "BROWSER_LOGIN_ENABLED": "false", "DEMO_MODE": "true",
        "SECURITY_DIR": security_dir, "QDRANT_URL": qdrant_url,
        "LLM_API_KEY": key, "LLM_PROVIDER": "openai_compatible",
        "LLM_BASE_URL": values.get("LLM_BASE_URL") or "https://tokenhub.tencentmaas.com/v1",
        "LLM_MODEL": values.get("LLM_MODEL") or "glm-5.3-flash",
        "LLM_REASONING_EFFORT": values.get("LLM_REASONING_EFFORT") or "low",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    }
    if hf_home is not None:
        if not Path(hf_home).is_absolute() or any(c in hf_home for c in "\r\n\x00"):
            raise ValueError("Embedding cache must be an absolute server path")
        config["HF_HOME"] = hf_home
    return config


RECEIVER = r'''
import json, os, secrets, sys, tempfile
from pathlib import Path
from dotenv import dotenv_values, set_key
target = Path(sys.argv[1])
if not target.is_absolute() or not target.parent.is_dir() or target.is_symlink():
    raise SystemExit("Invalid configuration destination")
incoming = json.load(sys.stdin)
allowed = {"APP_PUBLIC_URL", "BROWSER_LOGIN_ENABLED", "DEMO_MODE", "SECURITY_DIR", "QDRANT_URL",
           "LLM_API_KEY", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_REASONING_EFFORT",
           "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}
if set(incoming) not in (allowed, allowed | {"HF_HOME"}) or any(not isinstance(v, str) or chr(0) in v for v in incoming.values()):
    raise SystemExit("Invalid configuration payload")
if "HF_HOME" in incoming and (not Path(incoming["HF_HOME"]).is_absolute() or not Path(incoming["HF_HOME"]).is_dir()):
    raise SystemExit("Embedding cache directory does not exist")
old = dotenv_values(target) if target.is_file() else {}
secret = old.get("APP_SECRET_KEY") or secrets.token_urlsafe(48)
if len(secret) < 32:
    raise SystemExit("Existing preview secret is too short; explicit operator repair required")
descriptor, temporary = tempfile.mkstemp(prefix=".preview-config-", dir=target.parent)
os.close(descriptor)
try:
    for name, value in {"APP_SECRET_KEY": secret, **incoming}.items():
        set_key(temporary, name, value, quote_mode="always")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print("Preview model/demo config updated; key redacted; file mode 0600")
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(".env"))
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--remote-python", required=True)
    parser.add_argument("--remote-config", required=True)
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--security-dir", required=True)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6335")
    parser.add_argument("--hf-home", help="Existing server Hugging Face cache; no model download")
    args = parser.parse_args()
    config = preview_config(dotenv_values(args.source), args.public_url, args.security_dir, args.qdrant_url, args.hf_home)
    command = f"{shlex.quote(args.remote_python)} -c {shlex.quote(RECEIVER)} {shlex.quote(args.remote_config)}"
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.ssh_host, command],
                            input=json.dumps(config), text=True, capture_output=True)
    if result.returncode:
        # Do not echo remote stderr or the payload in case a library included a value.
        raise SystemExit("Remote preview configuration failed; credentials not displayed")
    print("Preview model/demo configuration synced over SSH; credentials not displayed")


if __name__ == "__main__":
    main()
