# mcp-tool

Maps MCP servers tools to CLI subcommands, providing progressive disclosure of MCP tools for Agents.

## Introduction

`mcp-tool` connects to configured MCP servers and converts their exposed **tools** into standard CLI subcommands.
For example, server `filesystem` tool `read_file` → `mcp-tool filesystem__read_file`

## Quick Start

### 1. View Available Tools

```bash
# List tools from all loaded servers
mcp-tool
```

### 2. View Tool Arguments

```bash
# View usage and arguments for a specific tool
mcp-tool fetch__fetch --help
```

### 3. Run a Tool

Supports two ways of passing arguments: **Flags** (Recommended) and **JSON**.

```bash
# Method 1: Using Flags (Automatically generated from schema)
mcp-tool fetch__fetch --url "https://example.com"

# Method 2: Using JSON
mcp-tool fetch__fetch --json '{"url": "https://example.com"}'
```

## Configuration

`mcp-tool` loads and merges configurations from the following locations in order:
1. `~/.mcp.json`
2. `./.claude/mcp.json`
3. `./mcp.json`

Format is the same as standard MCP:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "uvx",
      "args": ["mcp-server-fs", "--root", "."]
    }
  }
}
```

## Advanced Usage

### Argument Passing
Besides `--json`, reading from file or pipe is also supported:

- `--json-file args.json`: Read from file
- `--json-stdin`: Read from stdin (e.g., `echo '...' | mcp-tool ... --json-stdin`)

> Note: Flag arguments take precedence over same-named fields in JSON.

### Output Control
Default output is text format, suitable for human reading. For script processing, you can force JSON output:

```bash
mcp-tool <cmd> --output json
```

## Installation

This project is managed using [uv](https://docs.astral.sh/uv/) and requires Python >= 3.10.

```bash
# Run in development mode
mcp-tool --help
```
