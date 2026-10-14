"""Serve an existing isolated demo through a private Tailscale Serve gateway."""
import argparse
import os
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--security-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--qdrant-url', required=True)
    parser.add_argument('--public-url', required=True)
    parser.add_argument('--allowed-login', action='append', required=True)
    parser.add_argument('--port', type=int, default=17862)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be 1024..65535')
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=True)
    os.environ.update(QDRANT_URL=args.qdrant_url, CUDA_VISIBLE_DEVICES='', LLM_PLANNER_ENABLED='false')
    import torch
    torch.set_num_threads(4)
    from contextledger.interfaces.tailnet_preview import TailnetPreview
    from contextledger.interfaces.web import create_app
    from waitress import serve
    local = f'http://127.0.0.1:{args.port}'
    app = create_app(args.out / 'canonical.sqlite', args.security_dir,
                     config={'DEMO_MODE': True, 'DEMO_AUTO_ENTRY': True, 'BROWSER_LOGIN_ENABLED': False,
                             'PUBLIC_URL': local, 'SESSION_COOKIE_SECURE': True})
    gateway = TailnetPreview(app, public_url=args.public_url, local_url=local,
                            allowed_logins=args.allowed_login)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        serve(gateway, host='127.0.0.1', port=args.port, threads=8, channel_timeout=240)
    finally:
        app.extensions['document_updates'].close()


if __name__ == '__main__':
    main()
