# illume-mcp

A local stdio launcher for the hosted [Illume](https://illume.tejasnasa.me) MCP server. It is for
MCP clients that can only start a local command and cannot connect to a remote HTTP server or set
an `Authorization` header. The launcher connects to the hosted server with your token and forwards
everything: tools, resources, prompts and progress notifications pass through unchanged, so the
tool list is the hosted tool list. Nothing runs locally besides the proxy.

## Setup

Create a token in Illume under Settings, then register the launcher with your client. The token is
read from the `ILLUME_MCP_TOKEN` environment variable only; there is deliberately no `--token`
flag, because a token on the command line shows up in the process list and in shell history.

```bash
ILLUME_MCP_TOKEN=ilm_... \
  uvx --from "git+https://github.com/tejasnasa/illume#subdirectory=mcp-local" illume-mcp
```

In a client config that launches stdio servers (Claude Desktop, Cursor, and similar):

```json
{
  "mcpServers": {
    "illume": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/tejasnasa/illume#subdirectory=mcp-local",
        "illume-mcp"
      ],
      "env": { "ILLUME_MCP_TOKEN": "ilm_..." }
    }
  }
}
```

With Claude Code:

```bash
claude mcp add illume --env ILLUME_MCP_TOKEN=ilm_... -- \
  uvx --from "git+https://github.com/tejasnasa/illume#subdirectory=mcp-local" illume-mcp
```

## Options

| Option  | Default                             | Meaning                               |
| ------- | ----------------------------------- | ------------------------------------- |
| `--url` | `https://illume-api.tejasnasa.me`   | The Illume API; `/mcp` is appended.   |

## Errors

The launcher exits non-zero and explains on stderr when `ILLUME_MCP_TOKEN` is not set, or when the
server answers 401 because the token is invalid, revoked or expired. The token is never printed.

## Development

The package depends only on `mcp` and imports nothing from the Illume server. Its tests start the
real server against the test stack, so they run from the server's environment:

```bash
make test-infra
cd server && uv run pytest ../mcp-local/tests
```
