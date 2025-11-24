from __future__ import annotations

from pathlib import Path
from typing import Any

from click.testing import CliRunner

import mcp_cli.config as config_mod
import mcp_cli.main as main_mod
from mcp_cli.client import ToolDescriptor
from mcp_cli.config import MergedConfig, ServerConfig
from mcp_cli.main import cli


def test_load_merged_config_with_sample_mcp_json(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Ensure that load_merged_config picks up the example mcp.json.

    This test uses the actual mcp.json from the repository root, but runs in
    a temporary working directory by symlinking the file. This avoids any
    dependency on the caller's CWD.
    """

    repo_root = Path(__file__).resolve().parent.parent
    source_config = repo_root / "mcp.json"
    assert source_config.is_file(), "Expected mcp.json to exist at repository root"

    # Symlink mcp.json into the temporary directory so that the loader can
    # operate on a controlled cwd.
    target_config = tmp_path / "mcp.json"
    target_config.write_text(
        source_config.read_text(encoding="utf-8"), encoding="utf-8"
    )

    merged = config_mod.load_merged_config(cwd=tmp_path)

    # The sample config defines three servers: fetch, everything and exa (HTTP).
    assert set(merged.servers.keys()) == {"fetch", "everything", "exa"}

    fetch_cfg = merged.servers["fetch"]
    assert fetch_cfg.command == "uvx"
    assert fetch_cfg.args == ["mcp-server-fetch"]

    exa_cfg = merged.servers["exa"]
    assert exa_cfg.type == "http"
    assert exa_cfg.url == "https://mcp.exa.ai/mcp"
    assert exa_cfg.headers == {}


def test_help_sections_and_parameters(monkeypatch: Any) -> None:
    """Verify that help output contains custom sections and parameter mapping."""

    # Prepare a fake merged configuration and tool descriptor so we do not
    # start real MCP servers during tests.
    merged = MergedConfig(
        servers={
            "filesystem": ServerConfig(
                name="filesystem", command="dummy", args=[], env={}
            ),
        }
    )

    descriptor = ToolDescriptor(
        server_name="filesystem",
        tool_name="read_file",
        description="Read a file from the filesystem.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "max_length": {
                    "type": "integer",
                    "description": "Maximum bytes to read",
                },
                "raw": {
                    "type": "boolean",
                    "description": "Return raw bytes instead of text",
                },
            },
            "required": ["path"],
        },
        title=None,
    )

    def fake_load_merged_config(cwd: Path | None = None) -> MergedConfig:  # type: ignore[override]
        return merged

    async def fake_discover_tools(config: MergedConfig) -> list[ToolDescriptor]:  # type: ignore[override]
        return [descriptor]

    monkeypatch.setattr(main_mod, "load_merged_config", fake_load_merged_config)
    monkeypatch.setattr(main_mod, "discover_tools", fake_discover_tools)

    runner = CliRunner()

    # Root help should show the custom heading.
    result_root = runner.invoke(cli, ["--help"])
    assert result_root.exit_code == 0
    assert "Available MCP Tools" in result_root.output
    assert "filesystem__read_file" in result_root.output

    # Tool-specific help should contain a Parameters section with schema
    # derived flags and an Options section with generic flags.
    result_cmd = runner.invoke(cli, ["filesystem__read_file", "--help"])
    assert result_cmd.exit_code == 0

    output = result_cmd.output
    assert "Parameters:" in output
    # Flags derived from the schema.
    assert "--path" in output
    assert "--max_length" in output
    assert "--raw / --no-raw" in output

    # Generic options remain in the Options section.
    assert "Options:" in output
    assert "--json" in output
    assert "--json-file" in output
    assert "--json-stdin" in output
    assert "--output" in output

    # Help subcommand should behave like --help.
    result_help_root = runner.invoke(cli, ["help"])
    assert result_help_root.exit_code == 0
    assert "Available MCP Tools" in result_help_root.output

    result_help_cmd = runner.invoke(cli, ["help", "filesystem__read_file"])
    assert result_help_cmd.exit_code == 0
    assert "Parameters:" in result_help_cmd.output
