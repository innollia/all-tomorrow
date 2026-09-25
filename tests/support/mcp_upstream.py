"""Two independent MCP upstream fixtures with deliberately colliding tool names."""

import sys

from fastmcp import FastMCP


name, port = sys.argv[1], int(sys.argv[2])
server = FastMCP(name)


@server.tool(name="identify")
def identify() -> str:
    return name


@server.tool(name="echo_canary")
def echo_canary(value: str, output_override: str = "") -> str:
    if output_override:
        return output_override
    return value


if __name__ == "__main__":
    server.run(transport="http", host="127.0.0.1", port=port, show_banner=False)
