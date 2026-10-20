#!/usr/bin/env python3
"""Retired closeout for the former Agent/Profile execution plugins.

The controlled closeout drove `ordessa.agent`, `ordessa.profile`, session
configuration overlays, and the old submission journal. Those authorities
are retired. The current default product exposes the Pacthold Agent `/3`
contract; managed input and Profile application remain unavailable without
their current trusted ports. This command intentionally exits before opening
any database or starting a service.
"""

raise SystemExit(
    "retired: closeout depended on AgentSubmissionService/ProfileCore; "
    "no current managed-input or Profile-application owner is wired")
