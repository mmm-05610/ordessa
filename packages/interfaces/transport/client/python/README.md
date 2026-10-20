# Python wire client

The independently installed `ordessa-system-access-client` is shared by CLI and MCP. It owns bounded wire requests and schema checks, has no domain or app dependency, and never retries effectful requests after an unknown outcome. Closing a client does not close a backend Unit.
