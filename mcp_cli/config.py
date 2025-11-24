"""Configuration loading and merging for mcp-tool.

This module is responsible for locating MCP configuration files, parsing
their contents, and merging the configured MCP servers into a single view.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MCP_SERVERS_KEY = "mcpServers"


class ConfigError(Exception):
    """Base exception for configuration-related errors."""


class ConfigNotFoundError(ConfigError):
    """Raised when no usable MCP configuration can be found."""


class InvalidConfigError(ConfigError):
    """Raised when an MCP configuration file is malformed or invalid."""


@dataclass
class ServerConfig:
    """Configuration for a single MCP server.

    Attributes:
        name: Logical name of the server as used in configuration.
        command: Executable used to start the MCP server (stdio servers only).
        args: Command-line arguments passed to the executable (stdio servers only).
        env: Environment variables provided when starting the server (stdio servers only).
        type: Transport type, currently ``"stdio"`` (default) or ``"http"``.
        url: Endpoint URL for HTTP-based servers.
        headers: HTTP headers to send when connecting to HTTP-based servers.
        timeout: Optional HTTP timeout in seconds for HTTP servers.
        sse_read_timeout: Optional SSE read timeout in seconds for HTTP servers.
    """

    name: str
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    type: str = "stdio"
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: Optional[float] = None
    sse_read_timeout: Optional[float] = None


@dataclass
class MergedConfig:
    """Merged MCP configuration across all discovered configuration files."""

    servers: Dict[str, ServerConfig]


def get_default_config_paths(cwd: Optional[Path] = None) -> List[Path]:
    """Return existing configuration file paths in priority order.

    The search order (from lowest to highest priority) is:
      1. ~/.mcp.json
      2. ./ .claude/mcp.json
      3. ./ mcp.json

    Args:
        cwd: Optional working directory. If not provided, uses the current
            working directory.

    Returns:
        A list of existing configuration file paths in ascending priority
        order.
    """

    base_dir = cwd or Path.cwd()

    home_config = Path.home() / ".mcp.json"
    claude_config = base_dir / ".claude" / "mcp.json"
    local_config = base_dir / "mcp.json"

    existing_paths: List[Path] = []
    for path in (home_config, claude_config, local_config):
        if path.is_file():
            existing_paths.append(path)
    return existing_paths


def _load_raw_configs(paths: List[Path]) -> List[Tuple[Path, Dict[str, Any]]]:
    """Load raw JSON configuration objects from the given file paths.

    Args:
        paths: List of configuration file paths to load.

    Returns:
        A list of `(path, data)` tuples for successfully loaded files.

    Raises:
        InvalidConfigError: If any configuration file contains invalid JSON
            or is not a JSON object.
    """

    raw_configs: List[Tuple[Path, Dict[str, Any]]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - unexpected I/O failure
            raise InvalidConfigError(f"Failed to read config file: {path}") from exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            message = f"Invalid JSON in config file: {path}"
            raise InvalidConfigError(message) from exc

        if not isinstance(data, dict):
            message = f"Config file must contain a JSON object: {path}"
            raise InvalidConfigError(message)

        raw_configs.append((path, data))

    return raw_configs


def _merge_server_maps(
    configs: List[Tuple[Path, Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    """Merge `mcpServers` maps from multiple configuration objects.

    Later configurations override earlier ones at the server level. For a
    server that appears in multiple files, the later file wins for most keys,
    while the `env` mapping is shallow-merged so that later values override
    earlier ones for the same keys.

    Args:
        configs: A list of `(path, data)` tuples representing raw configs.

    Returns:
        A mapping from server name to a merged server configuration dict.
    """

    merged: Dict[str, Dict[str, Any]] = {}

    for _path, data in configs:
        servers_obj = data.get(MCP_SERVERS_KEY)
        if servers_obj is None:
            continue
        if not isinstance(servers_obj, dict):
            raise InvalidConfigError("'mcpServers' must be a JSON object when present.")

        for server_name, server_value in servers_obj.items():
            if not isinstance(server_name, str):
                raise InvalidConfigError(
                    "Server names in 'mcpServers' must be strings."
                )
            if not isinstance(server_value, dict):
                message = f"Server '{server_name}' configuration must be a JSON object."
                raise InvalidConfigError(message)

            existing = merged.get(server_name)
            if existing is None:
                merged[server_name] = dict(server_value)
                continue

            combined: Dict[str, Any] = dict(existing)

            # Shallow-merge environment variables if present in either config.
            existing_env = existing.get("env")
            new_env = server_value.get("env")
            if isinstance(existing_env, dict) or isinstance(new_env, dict):
                env_merged: Dict[str, Any] = {}
                if isinstance(existing_env, dict):
                    env_merged.update(existing_env)
                if isinstance(new_env, dict):
                    env_merged.update(new_env)
                combined["env"] = env_merged

            # For all other keys, later config wins.
            for key, value in server_value.items():
                if key == "env":
                    continue
                combined[key] = value

            merged[server_name] = combined

    return merged


def _server_from_mapping(name: str, data: Dict[str, Any]) -> ServerConfig:
    """Create a :class:`ServerConfig` instance from a raw mapping.

    The configuration supports multiple transport types:

    * Stdio (default):
      * ``command``: required non-empty string.
      * ``args``: optional list of strings.
      * ``env``: optional object map of string keys and values.
      * Optional ``type": "stdio"`` for explicitness.

    * HTTP (StreamableHTTP):
      * ``type": "http"`` (case-insensitive).
      * ``url``: required non-empty string.
      * ``headers``: optional object map of string keys and values.
      * ``timeout`` / ``sseReadTimeout`` (or ``sse_read_timeout``): optional numbers in seconds.

    Args:
        name: Logical server name.
        data: Raw server configuration mapping.

    Returns:
        A validated :class:`ServerConfig` instance.

    Raises:
        InvalidConfigError: If required fields are missing or of the wrong type.
    """

    raw_type = data.get("type", "stdio")
    if not isinstance(raw_type, str):
        message = f"Server '{name}' has an invalid 'type' field; expected a string."
        raise InvalidConfigError(message)

    server_type = raw_type.lower()

    # HTTP-based StreamableHTTP server.
    if server_type == "http":
        url_value = data.get("url")
        if not isinstance(url_value, str) or not url_value:
            message = (
                f"Server '{name}' is missing a non-empty 'url' field for HTTP server."
            )
            raise InvalidConfigError(message)

        headers_value = data.get("headers", {})
        headers: Dict[str, str] = {}
        if isinstance(headers_value, dict):
            for key, value in headers_value.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    message = (
                        f"Server '{name}' has non-string HTTP header name or value."
                    )
                    raise InvalidConfigError(message)
                headers[key] = value
        elif headers_value is not None:
            message = f"Server '{name}' has an invalid 'headers' field; expected an object or null."
            raise InvalidConfigError(message)

        timeout_value = data.get("timeout")
        timeout: Optional[float] = None
        if timeout_value is not None:
            if not isinstance(timeout_value, (int, float)):
                message = f"Server '{name}' has an invalid 'timeout' field; expected a number."
                raise InvalidConfigError(message)
            timeout = float(timeout_value)

        sse_timeout_raw = data.get("sseReadTimeout", data.get("sse_read_timeout"))
        sse_read_timeout: Optional[float] = None
        if sse_timeout_raw is not None:
            if not isinstance(sse_timeout_raw, (int, float)):
                message = f"Server '{name}' has an invalid 'sseReadTimeout' field; expected a number."
                raise InvalidConfigError(message)
            sse_read_timeout = float(sse_timeout_raw)

        return ServerConfig(
            name=name,
            type="http",
            url=url_value,
            headers=headers,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
        )

    # Default to stdio-based servers.
    if server_type != "stdio":
        message = f"Server '{name}' has unsupported 'type' value '{raw_type}'."
        raise InvalidConfigError(message)

    command_value = data.get("command")
    if not isinstance(command_value, str) or not command_value:
        message = f"Server '{name}' is missing a non-empty 'command' field."
        raise InvalidConfigError(message)

    args_value = data.get("args", [])
    if not isinstance(args_value, list) or not all(
        isinstance(item, str) for item in args_value
    ):
        message = (
            f"Server '{name}' has an invalid 'args' field; expected a list of strings."
        )
        raise InvalidConfigError(message)

    env_value = data.get("env", {})
    env: Dict[str, str] = {}
    if isinstance(env_value, dict):
        for key, value in env_value.items():
            if not isinstance(key, str) or not isinstance(value, str):
                message = (
                    f"Server '{name}' has non-string environment variable key or value."
                )
                raise InvalidConfigError(message)
            env[key] = value
    elif env_value is not None:
        message = (
            f"Server '{name}' has an invalid 'env' field; expected an object or null."
        )
        raise InvalidConfigError(message)

    return ServerConfig(
        name=name, command=command_value, args=list(args_value), env=env, type="stdio"
    )


def load_merged_config(cwd: Optional[Path] = None) -> MergedConfig:
    """Load and merge MCP configuration from the standard config locations.

    Args:
        cwd: Optional working directory. If not provided, uses the current
            working directory.

    Returns:
        A `MergedConfig` instance containing all discovered servers.

    Raises:
        ConfigNotFoundError: If no configuration files are found or if none of
            the found files define any servers.
        InvalidConfigError: If any configuration file is malformed.
    """

    base_dir = cwd or Path.cwd()

    # Compute the three canonical search locations for user feedback.
    candidate_paths = [
        Path.home() / ".mcp.json",
        base_dir / ".claude" / "mcp.json",
        base_dir / "mcp.json",
    ]

    existing_paths = get_default_config_paths(base_dir)
    if not existing_paths:
        locations = ", ".join(str(path) for path in candidate_paths)
        message = (
            "No MCP configuration files found. Looked for the following paths: "
            f"{locations}."
        )
        raise ConfigNotFoundError(message)

    raw_configs = _load_raw_configs(existing_paths)
    server_maps = _merge_server_maps(raw_configs)
    if not server_maps:
        message = (
            "No 'mcpServers' entries were found in any configuration file. "
            "Please define at least one server in mcp.json."
        )
        raise ConfigNotFoundError(message)

    servers: Dict[str, ServerConfig] = {}
    for server_name, server_data in server_maps.items():
        servers[server_name] = _server_from_mapping(server_name, server_data)

    return MergedConfig(servers=servers)
