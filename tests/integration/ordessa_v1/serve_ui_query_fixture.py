"""Retained actual HTTP/SQLite query peer; seeded records are not approvals."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from apps.server.tests.test_engineering_slice import runtime, SCOPE
from apps.server.tests.test_engineering_confirmation_queries import records
from ordessa_interfaces.http import create_app
from ordessa_server.__main__ import bind_loopback_socket, serving_origin
import uvicorn

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff', type=Path, required=True)
    args = parser.parse_args()
    if args.handoff.exists():
        raise SystemExit('existing_handoff_refused')
    root = Path(tempfile.mkdtemp(prefix='ordessa-v1-ui-query-'))
    os.chmod(root, 0o700)
    args.handoff.parent.mkdir(parents=True, exist_ok=True)
    with args.handoff.with_suffix('.root.json').open('x') as stream:
        stream.write(json.dumps({'root':str(root), 'retained_for_audit':True,
            'cleanup_requires_separate_authorization':True})+'\n')
    fixture = runtime.__wrapped__(root)
    host = next(fixture)
    sock = None
    try:
        notice, intent, challenge, grant, _ = records.__wrapped__(host)
        token_path = root/'machine-token'
        token_path.write_text(host.token)
        os.chmod(token_path, 0o600)
        sock = bind_loopback_socket(0)
        info = {'origin':serving_origin(sock), 'scope':asdict(SCOPE),
            'notice_ref':asdict(notice.ref), 'approval_ref':asdict(grant.ref),
            'intent_id':intent.intent_id, 'challenge_id':challenge.challenge_id,
            'token_locator':str(token_path), 'data_root':str(root), 'pid':os.getpid(),
            'assurance':'machine bearer; seeded query fixture; no human approval',
            'lifetime_seconds':900, 'product_complete':False}
        args.handoff.parent.mkdir(parents=True, exist_ok=True)
        def announce():
            args.handoff.write_text(json.dumps(info, indent=2)+'\n')
            print(json.dumps({'status':'listening','origin':info['origin'],'handoff':str(args.handoff)}), flush=True)
        uvicorn.Server(uvicorn.Config(create_app(host, on_bound=announce), log_config=None)).run(sockets=[sock])
    finally:
        if sock is not None:
            sock.close()
        fixture.close()
        args.handoff.with_suffix('.stopped.json').write_text(json.dumps({'stopped':True,'pid':os.getpid(),'data_root':str(root),'files_retained':True})+'\n')

if __name__ == '__main__':
    main()
