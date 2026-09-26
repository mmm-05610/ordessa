"""Order 58: managed skill and MCP assets, separate from configuration.

Assets live under their own root, are content-addressed (tree digest v1), and
are materialised as read-only projections into a Harness's declared slots.
Nothing here writes a user's native configuration: that rule is the reason
this package exists apart from the deployment/projection code.
"""
