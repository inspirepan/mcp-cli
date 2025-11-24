## Overview

This repository implements the `mcp-tool` command-line interface that exposes
MCP servers' tools as local CLI subcommands. The codebase is intentionally
small and focused; the goal of this document is to make the overall structure
and responsibilities explicit.

The project is organized as a single Python package, `mcp_cli`, plus tests:

- `mcp_cli/`: CLI entrypoint and core logic
- `tests/`: Pytest-based tests for config loading and CLI help behaviour

Python version is 3.10+, with full type hints and standard type checking via
Pyright (see `pyproject.toml`).

## Modules and Responsibilities

- `mcp_cli.main`
  - CLI wiring and the `McpToolCLI` multi-command entrypoint
  - Dynamic discovery of tools and creation of subcommands
  - Argument parsing for JSON payloads and output formatting
  - User-friendly `help` behaviour (`help` as command or suffix)

- `mcp_cli.client`
  - `McpServerClient`: thin wrapper over the MCP Python SDK for one server
  - `ToolDescriptor`: dataclass representing a single tool on a server
  - Discovery helpers: `discover_tools`, `discover_tools_for_server`
  - Abstracts over stdio vs HTTP transports

- `mcp_cli.config`
  - Configuration model types: `ServerConfig`, `MergedConfig`
  - Discovery of config files (home, `.claude/mcp.json`, local `mcp.json`)
  - Validation and merging of `mcpServers` entries across files
  - Clear error reporting via `ConfigError` and subclasses

- `mcp_cli.schema`
  - `PropertySpec`: dataclass describing how a JSON Schema field maps to CLI
    options
  - `build_property_specs`: maps *simple* JSON Schemas to Click options,
    leaving complex inputs to JSON-based arguments

## Key Classes and Their Design

### `McpToolCLI` (in `mcp_cli.main`)

`McpToolCLI` is a `click.MultiCommand` subclass that exposes each MCP tool as
a subcommand. Design highlights:

- Caches configuration (`MergedConfig`) and discovered tools (`ToolDescriptor`
  list) for the lifetime of a single CLI process.
- Uses `_load_config()` as a single place to load configuration with
  consistent, user-facing error handling.
- `list_commands()` computes available subcommand names in the form
  `<server>__<tool>`.
- `get_command()` resolves a subcommand name to a Click `Command` by:
  - Optionally limiting discovery to a single server to avoid starting
    unrelated MCP servers.
  - Identifying the matching `ToolDescriptor`.
  - Delegating to `_build_tool_command()` to construct the actual command.
- `format_commands()` customizes the root help output to show all available
  tools in a dedicated "Available MCP Tools" section.

### `ToolCommand` (in `mcp_cli.main`)

`ToolCommand` is a small Click `Command` subclass with a clearer help layout:

- Separates schema-derived tool parameters from generic flags.
- Renders two sections in help:
  - `Parameters`: options derived from the tool's input JSON Schema.
  - `Options`: generic flags such as `--json` and `--output`.
- When an input schema is available, renders a pretty-printed copy of the
  JSON Schema in an "Input schema" section (using Rich for TTY output).

### `McpServerClient` (in `mcp_cli.client`)

`McpServerClient` encapsulates the interaction with a single MCP server:

- Initialized with a validated `ServerConfig` instance.
- `initialize()` chooses between stdio and HTTP transports based on the
  `type` field and starts a `ClientSession`.
- `list_tools()` converts the raw response into a list of `ToolDescriptor`
  instances.
- `call_tool()` executes a tool by name with a JSON-compatible argument
  mapping.
- `cleanup()` shuts down the client session using an `AsyncExitStack`.

This design keeps transport and session management out of the CLI layer while
remaining a thin wrapper around the underlying MCP SDK.

### Configuration Types (in `mcp_cli.config`)

- `ServerConfig`
  - Represents user-defined configuration for one server.
  - Supports two transport types:
    - `stdio` (default): `command`, `args`, `env`.
    - `http`: `url`, `headers`, `timeout`, `sse_read_timeout`.
  - Constructed via `_server_from_mapping()` which validates user input and
    surfaces clear error messages.

- `MergedConfig`
  - Simple container holding a `dict[str, ServerConfig]` mapping by name.

### Schema Mapping (in `mcp_cli.schema`)

- `PropertySpec`
  - Describes how a single JSON Schema property becomes a CLI flag.
  - Fields include the original property name, CLI flag (`--foo`), logical
    type, required flag, enum choices, and description.

- `build_property_specs()`
  - Accepts a JSON Schema for tool input and returns a list of `PropertySpec`
    instances for *simple* scalar fields.
  - Skips non-object schemas, non-dict `properties`, and fields that are not
    `string`/`integer`/`number`/`boolean`.
  - Reserved names (`json`, `json_file`, `json_stdin`, `output`) are ignored
    to avoid collisions with internal options.
  - Enum handling is limited to simple string enums, which are exposed as
    `click.Choice` options.

## CLI Flow

At a high level, a typical command invocation follows this path:

1. User runs `mcp-tool <server>__<tool> [flags]`.
2. `cli` (an instance of `McpToolCLI`) processes arguments, including
   `help`-style forms such as `mcp-tool help <command>`.
3. `McpToolCLI.get_command()` ensures configuration is loaded and tools are
   discovered, then creates a `ToolCommand` via `_build_tool_command()`.
4. When the command body runs:
   - JSON arguments are parsed from `--json`, `--json-file`, or `--json-stdin`.
   - Schema-derived CLI flags are merged over JSON arguments.
   - `_run_tool()` starts an `McpServerClient`, calls the tool, and prints the
     result via `_print_result()`.

## Testing and Conventions

- Tests live under `tests/` and currently focus on:
  - `load_merged_config()` behaviour with the sample `mcp.json`.
  - CLI help output: custom sections and parameter mapping.
- Type hints are required for all public functions and methods.
- Keep functions small and focused; use helper functions or small classes when
  logic starts to grow.
- When adding new behaviour, prefer reusing existing abstractions:
  - Use `ServerConfig`/`MergedConfig` for configuration.
  - Use `McpServerClient` for server interaction.
  - Use `PropertySpec`/`build_property_specs` for schema-to-CLI mappings.
