#!/usr/bin/env python3
"""Retired probe for the former Profile/session-overlay execution chain.

The probe used to create a Profile, open native channels, and inspect the
old Profile SQLite schema. That authority and its wire methods are retired.
Do not run this probe against a user data root or recreate its former chain.
Current Profile catalog reads are exposed through Pacthold's Agent public
contract; managed configuration and input application remain unavailable
until a current owner supplies the required ports.
"""

raise SystemExit(
    "retired: Profile session isolation depended on ProfileCore/session overlays; "
    "no current managed configuration projection is available")
