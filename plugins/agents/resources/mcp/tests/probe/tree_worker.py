"""Descendant process for the T03 tree/cleanup tests.

Usage: ``python tree_worker.py <role> <pidfile>`` - ``child`` records its pid
then spawns the ``grand`` role (same process group, inherited); ``grand``
records its pid. Both then idle until killed. Each appends its pid as one
line to ``pidfile``.
"""
import os
import subprocess
import sys
import time

role, pids = sys.argv[1], sys.argv[2]
with open(pids, "a") as fh:
    fh.write(str(os.getpid()) + "\n")
    fh.flush()
if role == "child":
    # stdout/stderr to DEVNULL: descendants must never hold the MCP stdio
    # pipe open after the fake server itself exits.
    subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "tree_worker.py"), "grand", pids],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(300)
