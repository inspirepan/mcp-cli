"""Entry point and CLI wiring for the mcp-tool command."""

from __future__ import annotations

import asyncio
import json
import sys
from io import StringIO
from pathlib import Path
from typing import Any

import click
import mcp.types as types
from rich.console import Console
from rich.syntax import Syntax

from .client import McpServerClient, ToolDescriptor, discover_tools, discover_tools_for_server
from .config import ConfigError, ConfigNotFoundError, MergedConfig, load_merged_config
from .schema import build_property_specs


class McpToolCLI(click.MultiCommand):  # type: ignore[misc]
    """Dynamic CLI that exposes MCP tools as subcommands."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._merged_config: MergedConfig | None = None
        self._tool_descriptors: list[ToolDescriptor] | None = None
        self._config_error: Exception | None = None

    def _load_config(self) -> MergedConfig | None:
        """Load and cache the merged configuration with user-facing errors.

        When configuration loading fails, the exception is stored in
        ``self._config_error`` and ``None`` is returned so callers can
        short-circuit further work.
        """

        if self._merged_config is not None or self._config_error is not None:
            return self._merged_config

        try:
            merged_config = load_merged_config()
        except ConfigError as exc:
            click.echo(click.style(f"Configuration error: {exc}", fg="red"), file=sys.stderr)
            self._config_error = exc
            return None

        self._merged_config = merged_config
        return merged_config

    def _ensure_discovery(self) -> None:
        """Load configuration and discover tools if not already done."""

        if self._tool_descriptors is not None or self._config_error is not None:
            return

        merged_config = self._load_config()
        if merged_config is None:
            return

        try:
            descriptors = asyncio.run(discover_tools(merged_config))
        except Exception as exc:  # pragma: no cover - unexpected runtime failure
            click.echo(
                click.style(f"Error during tool discovery: {exc}", fg="red"),
                file=sys.stderr,
            )
            self._config_error = exc
            return

        self._merged_config = merged_config
        self._tool_descriptors = descriptors

    def _ensure_discovery_for_server(self, server_name: str) -> None:
        """Load configuration and discover tools for a single server.

        This is used by get_command to avoid starting unrelated MCP servers
        when invoking a specific tool subcommand.
        """

        if self._tool_descriptors is not None or self._config_error is not None:
            return

        merged_config = self._load_config()
        if merged_config is None:
            return

        if server_name not in merged_config.servers:
            message = f"Server '{server_name}' is not defined in configuration."
            self._config_error = ConfigNotFoundError(message)
            return

        try:
            descriptors = asyncio.run(discover_tools_for_server(merged_config, server_name))
        except Exception as exc:  # pragma: no cover - unexpected runtime failure
            click.echo(
                click.style(f"Error during tool discovery: {exc}", fg="red"),
                file=sys.stderr,
            )
            self._config_error = exc
            return

        self._tool_descriptors = descriptors

    def list_commands(self, ctx: click.Context) -> list[str]:  # type: ignore[override]
        """Return all available subcommand names.

        When configuration is missing or invalid, an empty list is returned
        and the root help text guides the user to configure servers.
        """

        self._ensure_discovery()
        if not self._tool_descriptors:
            return []

        names = [f"{tool.server_name}__{tool.tool_name}" for tool in self._tool_descriptors]
        return sorted(set(names))

    def get_command(self, ctx: click.Context, name: str) -> click.Command | None:  # type: ignore[override]
        """Return a click command for the given subcommand name."""

        # Special-case a `help` subcommand, which behaves similarly to
        # "git help" and can show either the root help or the help for a
        # specific tool command.
        if name == "help":

            @click.command(name="help")
            @click.argument("command_name", required=False)
            @click.pass_context
            def _help_command(inner_ctx: click.Context, command_name: str | None) -> None:
                parent_ctx = inner_ctx.parent
                if parent_ctx is None:
                    raise click.ClickException("Internal error: missing parent context for help command.")

                if not command_name:
                    click.echo(parent_ctx.get_help())
                    return

                cmd = self.get_command(parent_ctx, command_name)
                if cmd is None:
                    raise click.ClickException(f"Unknown command '{command_name}'.")

                cmd_ctx = click.Context(cmd, info_name=command_name, parent=parent_ctx)
                click.echo(cmd.get_help(cmd_ctx))

            return _help_command

        server_name: str | None = None
        if "__" in name:
            server_name = name.split("__", 1)[0]

        if server_name is not None:
            self._ensure_discovery_for_server(server_name)
        else:
            self._ensure_discovery()

        if self._config_error is not None:
            # Surface configuration errors immediately so they are visible even
            # when the user requests --help for the command.
            raise click.ClickException(str(self._config_error))

        if not self._tool_descriptors or self._merged_config is None:
            return None

        target_tool: ToolDescriptor | None = None
        for descriptor in self._tool_descriptors:
            if f"{descriptor.server_name}__{descriptor.tool_name}" == name:
                target_tool = descriptor
                break

        if target_tool is None:
            return None

        server_config = self._merged_config.servers.get(target_tool.server_name)
        if server_config is None:
            return None

        return _build_tool_command(name, server_config.name, target_tool.tool_name, target_tool)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:  # type: ignore[override]
        """Render the list of available MCP tools in the help output."""

        commands = self.list_commands(ctx)
        if not commands:
            return

        rows: list[tuple[str, str]] = []
        for name in commands:
            cmd = self.get_command(ctx, name)
            if cmd is None:
                continue
            rows.append((name, cmd.get_short_help_str()))

        if rows:
            with formatter.section(click.style("Available MCP Tools", fg="cyan", bold=True)):
                formatter.write_dl(rows)


class ToolCommand(click.Command):
    """Command subclass that separates schema parameters from generic options.

    In addition to standard Click help output, this command type renders an
    "Input schema" section and a dedicated "Parameters" section that lists
    options derived from the tool's JSON Schema.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._schema_param_names: set[str] = set()
        self._input_schema_text: str | None = None

    def set_schema_param_names(self, names: set[str]) -> None:
        """Mark which parameters come from the tool input schema."""

        self._schema_param_names = set(names)

    def set_input_schema_text(self, text: str) -> None:
        """Attach pretty-printed JSON Schema text for help rendering."""

        self._input_schema_text = text

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:  # type: ignore[override]
        """Render Parameters and Options sections separately.

        Parameters are the options derived from the tool's input schema, while
        Options are the generic flags (JSON arguments, output format, help).
        """

        schema_records: list[tuple[str, str]] = []
        option_records: list[tuple[str, str]] = []

        for param in self.get_params(ctx):
            record = param.get_help_record(ctx)
            if record is None:
                continue
            if param.name in self._schema_param_names:
                schema_records.append(record)
            else:
                option_records.append(record)

        if schema_records:
            with formatter.section(click.style("Parameters", fg="green", bold=True)):
                formatter.write_dl(schema_records)

        if option_records:
            with formatter.section(click.style("Options", fg="yellow", bold=True)):
                formatter.write_dl(option_records)

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:  # type: ignore[override]
        """Extend the default help with an "Input schema" section."""

        super().format_help(ctx, formatter)

        if self._input_schema_text:
            with formatter.section(click.style("Input schema", fg="magenta", bold=True)):
                for line in _format_json_schema_with_rich(self._input_schema_text):
                    formatter.write_text(line)


def _format_json_schema_with_rich(schema_text: str) -> list[str]:
    """Format JSON schema text with rich syntax highlighting when appropriate.

    When stdout is not a TTY, the original plain-text lines are returned to
    avoid leaking ANSI color codes into redirected or captured output.
    """

    try:
        if not sys.stdout.isatty():
            return schema_text.splitlines()
    except Exception:
        return schema_text.splitlines()

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True, color_system="auto")
    syntax = Syntax(schema_text, "json", word_wrap=False, theme="ansi_light")
    console.print(syntax)
    value = buffer.getvalue()
    return value.splitlines()


def _build_tool_command(
    command_name: str,
    server_name: str,
    tool_name: str,
    descriptor: ToolDescriptor,
) -> click.Command:
    """Create a click command that invokes the given MCP tool.

    The generated command supports JSON-based argument passing and, when the
    tool input schema is simple enough, also exposes individual fields as
    dedicated CLI flags.
    """

    property_specs = build_property_specs(descriptor.input_schema)

    def _command(**cli_kwargs: Any) -> None:
        """Execute the selected MCP tool as a CLI subcommand."""

        json_arg = cli_kwargs.pop("json", None)
        json_file = cli_kwargs.pop("json_file", None)
        json_stdin = bool(cli_kwargs.pop("json_stdin", False))
        output = str(cli_kwargs.pop("output", "text"))

        flag_args: dict[str, Any] = {}
        for spec in property_specs:
            if spec.param_name in cli_kwargs and cli_kwargs[spec.param_name] is not None:
                flag_args[spec.name] = cli_kwargs[spec.param_name]

        try:
            arguments = _parse_json_arguments(json_arg, json_file, json_stdin)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        # CLI flags override JSON-provided arguments for the same fields.
        arguments.update(flag_args)

        try:
            asyncio.run(_run_tool(server_name, tool_name, arguments, output))
        except ConfigError as exc:
            raise click.ClickException(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - unexpected runtime errors
            raise click.ClickException(f"Tool execution failed: {exc}") from exc

    # Apply dynamic options for schema-derived properties first, then generic options.
    cmd: click.Command = click.command(name=command_name, cls=ToolCommand)(_command)
    schema_param_names: set[str] = set()

    for spec in property_specs:
        option_kwargs: dict[str, Any] = {
            "help": spec.description or "",
            "required": spec.required,
        }

        if spec.choices is not None:
            option_kwargs["type"] = click.Choice(spec.choices, case_sensitive=False)
        elif spec.type == "integer":
            option_kwargs["type"] = int
        elif spec.type == "number":
            option_kwargs["type"] = float
        elif spec.type == "boolean":
            # Boolean flags are exposed as --name/--no-name style switches.
            schema_param_names.add(spec.name)
            cmd = click.option(
                f"--{spec.name}/--no-{spec.name}",
                default=False,
                help=spec.description or "",
            )(cmd)
            continue
        else:
            option_kwargs["type"] = str

        schema_param_names.add(spec.param_name)
        cmd = click.option(spec.cli_flag, spec.param_name, **option_kwargs)(cmd)

    # Generic JSON and output options.
    cmd = click.option(
        "--output",
        "output",
        type=click.Choice(["text", "json"], case_sensitive=False),
        default="text",
        show_default=True,
        help="Output format for tool results.",
    )(cmd)
    cmd = click.option(
        "--json-stdin",
        "json_stdin",
        is_flag=True,
        default=False,
        help="Read JSON arguments from standard input.",
    )(cmd)
    cmd = click.option(
        "--json-file",
        "json_file",
        type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
        required=False,
        help="Path to a JSON file containing arguments.",
    )(cmd)
    cmd = click.option(
        "--json",
        "json",
        type=str,
        required=False,
        help="Inline JSON arguments for the tool.",
    )(cmd)

    # Mark schema-derived parameters so that ToolCommand can render them in a
    # dedicated Parameters section.
    if isinstance(cmd, ToolCommand):
        cmd.set_schema_param_names(schema_param_names)

    # Enrich the command help with the original tool description. The input
    # schema itself is rendered via ToolCommand.format_help to preserve
    # newlines and indentation.
    description = descriptor.description or f"Execute tool '{tool_name}' on server '{server_name}'."
    help_parts = [description]
    if property_specs:
        help_parts.append(
            "Simple input fields are available as CLI flags when possible. "
            "More complex inputs should be provided via --json, --json-file or --json-stdin."
        )
    else:
        help_parts.append("Arguments should be provided as JSON via --json, --json-file or --json-stdin.")

    help_text = "\n\n".join(help_parts)
    cmd.help = help_text
    cmd.__doc__ = help_text
    if isinstance(cmd, ToolCommand):
        schema_text = json.dumps(descriptor.input_schema, ensure_ascii=False, indent=2)
        if schema_text and schema_text != "{}":
            cmd.set_input_schema_text(schema_text)
    return cmd


def _parse_json_arguments(
    json_arg: str | None,
    json_file: Path | None,
    json_stdin: bool,
) -> dict[str, Any]:
    """Parse JSON arguments from CLI options.

    Exactly one of ``json_arg``, ``json_file`` or ``json_stdin`` may be
    provided. When none are provided, an empty argument object is used.
    """

    sources_provided = sum(bool(value) for value in (json_arg, json_file, json_stdin))
    if sources_provided > 1:
        raise ValueError("Only one of --json, --json-file or --json-stdin may be used at a time.")

    raw: str | None = None
    if json_stdin:
        raw = sys.stdin.read()
    elif json_file is not None:
        raw = json_file.read_text(encoding="utf-8")
    elif json_arg is not None:
        raw = json_arg

    if raw is None or not raw.strip():
        return {}

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - trivial error path
        raise ValueError("Failed to parse JSON arguments.") from exc

    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be a JSON object.")

    return value


async def _run_tool(server_name: str, tool_name: str, arguments: dict[str, Any], output: str) -> None:
    """Execute a single tool call and print its result."""

    merged = load_merged_config()
    server_config = merged.servers.get(server_name)
    if server_config is None:
        message = f"Server '{server_name}' is not defined in configuration."
        raise ConfigNotFoundError(message)

    client = McpServerClient(server_config)
    try:
        await client.initialize()
        result = await client.call_tool(tool_name, arguments)
    finally:
        await client.cleanup()

    _print_result(result, output)


def _print_result(result: types.CallToolResult, output: str) -> None:
    """Print tool results in the requested format."""

    if output.lower() == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if not result.content:
        return

    for block in result.content:
        if isinstance(block, types.TextContent):
            click.echo(block.text.replace("\n\n", "\n"), nl=True)


cli = McpToolCLI(
    help=(
        "Expose MCP servers' tools as local CLI subcommands. "
        "Configure servers via mcp.json, .claude/mcp.json or ~/.mcp.json."
    )
)


def _rewrite_args_for_help(argv: list[str]) -> list[str]:
    """Rewrite arguments to support ``help`` as a subcommand or suffix.

    Supported patterns:

    * ``mcp-tool help`` → ``mcp-tool --help``
    * ``mcp-tool help <command>`` → ``mcp-tool <command> --help``
    * ``mcp-tool <command> help`` → ``mcp-tool <command> --help``
    """

    if not argv:
        return argv

    if argv[0] == "help":
        if len(argv) == 1:
            return ["--help"]
        return [argv[1]] + ["--help"] + argv[2:]

    if len(argv) >= 2 and argv[-1] == "help":
        return argv[:-1] + ["--help"]

    return argv


def main() -> None:
    """Execute the mcp-tool CLI."""

    args = _rewrite_args_for_help(sys.argv[1:])
    cli.main(args=args, standalone_mode=True)


if __name__ == "__main__":  # pragma: no cover
    main()
