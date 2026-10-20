"""Offline Codex declaration compiler probe, using the brand's current owner.

This tool no longer constructs an Environment, activates providers, invokes the
retired Graph validator, or accepts model credentials. It checks native compile
facts only; its output is not an Engineering validation/approval receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ordessa_harness_codex.native_channel import compile_config


def compile_plan(options):
    """Use the retained native compiler; never create process/session authority."""
    if type(options) is not dict:
        raise ValueError('configuration object required')
    encoded=json.dumps(options,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False)
    if len(encoded.encode('utf-8'))>65536:
        raise ValueError('configuration exceeds probe bound')
    result=compile_config(options)
    return {'schemaVersion':'codex-compile-probe/1','scope':'native-declaration-compile-only',
        'inputDigest':'sha256:'+hashlib.sha256(encoded.encode('utf-8')).hexdigest(),
        'compiled':result,'executionObserved':False,'engineeringAccepted':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        data=args.configuration.read_bytes()
        if len(data)>65536:raise ValueError('configuration exceeds probe bound')
        value=compile_plan(json.loads(data))
        print(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False))
    except (OSError,ValueError,TypeError):
        print('configuration_compile_refused')
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
