"""SDK-owned stdio fixture, separate from the task 1 submission."""

from mcp.server import MCPServer

server = MCPServer("assessment-mock")


@server.tool()
def fixture_ping() -> str:
    """Return a fixed value without file, network, or process access."""
    return "pong"


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
