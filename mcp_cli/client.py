"""MCP server client wrapper used by the mcp-tool CLI.

This module provides a thin abstraction over the MCP Python SDK in order to:

* Start MCP servers based on `ServerConfig` definitions.
* List tools available on each server.
* Execute a specific tool with JSON arguments.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import mcp.types as types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .config import MergedConfig, ServerConfig


@dataclass
class ToolDescriptor:
    """Description of a tool exposed by an MCP server.

    Attributes:
        server_name: Logical name of the MCP server.
        tool_name: Name of the tool as reported by the server.
        description: Human-readable description of the tool.
        input_schema: JSON Schema describing the tool input.
        title: Optional user-facing title if provided by the server.
    """

    server_name: str
    tool_name: str
    description: str
    input_schema: Dict[str, Any]
    title: Optional[str] = None


class McpServerClient:
    """Client wrapper around a single MCP server.

    This class is responsible for starting the server process, establishing a
    client session, listing tools, and executing tools. It is designed to be
    used within a single CLI invocation.
    """

    def __init__(self, config: ServerConfig) -> None:
        """Initialize a client for the given server configuration.

        Args:
            config: Server configuration containing command, args and env.
        """

        self._config: ServerConfig = config
        self._exit_stack: AsyncExitStack = AsyncExitStack()
        self._session: Optional[ClientSession] = None

    @property
    def name(self) -> str:
        """Return the logical name of the server."""

        return self._config.name

    async def initialize(self) -> None:
        """Start the MCP server connection and establish a client session."""

        server_type = getattr(self._config, "type", "stdio").lower()

        if server_type == "http":
            if not self._config.url:
                message = (
                    f"Server '{self._config.name}' is missing 'url' for HTTP transport."
                )
                raise RuntimeError(message)

            timeout = self._config.timeout if self._config.timeout is not None else 30.0
            sse_read_timeout = (
                self._config.sse_read_timeout
                if self._config.sse_read_timeout is not None
                else 60.0 * 5
            )

            http_client_cm = streamablehttp_client(
                url=self._config.url,
                headers=self._config.headers or {},
                timeout=timeout,
                sse_read_timeout=sse_read_timeout,
                terminate_on_close=True,
            )

            read, write, _get_session_id = await self._exit_stack.enter_async_context(
                http_client_cm
            )
            session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self._session = session
            return

        # Default to stdio-based transport.
        if not self._config.command:
            message = f"Server '{self._config.name}' is missing 'command' for stdio transport."
            raise RuntimeError(message)

        # Resolve the executable path when possible, but fall back to the raw
        # command string if it is not found in PATH.
        resolved_command = shutil.which(self._config.command) or self._config.command

        merged_env: Optional[Dict[str, str]] = None
        if self._config.env:
            merged_env = dict(os.environ)
            merged_env.update(self._config.env)

        server_params = StdioServerParameters(
            command=resolved_command,
            args=self._config.args,
            env=merged_env,
        )

        stdio_transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read, write = stdio_transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session

    async def list_tools(self) -> List[ToolDescriptor]:
        """Return all tools exposed by this server.

        Returns:
            A list of :class:`ToolDescriptor` instances for the server.

        Raises:
            RuntimeError: If the client has not been initialized.
        """

        if self._session is None:
            message = f"Server '{self._config.name}' not initialized. Call initialize() first."
            raise RuntimeError(message)

        tools_response = await self._session.list_tools()
        descriptors: List[ToolDescriptor] = []

        for item in tools_response:
            if not isinstance(item, tuple):
                continue
            kind, payload = item
            if kind != "tools":
                continue

            for tool in payload:
                description = getattr(tool, "description", "") or ""
                input_schema = getattr(tool, "inputSchema", {}) or {}
                title = getattr(tool, "title", None)

                descriptors.append(
                    ToolDescriptor(
                        server_name=self._config.name,
                        tool_name=tool.name,
                        description=description,
                        input_schema=input_schema,
                        title=title,
                    )
                )

        return descriptors

    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> types.CallToolResult:
        """Execute a tool on this server.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool input arguments as a JSON-compatible mapping.

        Returns:
            The raw result returned by the MCP server.

        Raises:
            RuntimeError: If the client has not been initialized.
        """

        if self._session is None:
            message = f"Server '{self._config.name}' not initialized. Call initialize() first."
            raise RuntimeError(message)

        return await self._session.call_tool(tool_name, arguments)

    async def cleanup(self) -> None:
        """Close the client session and stop the server process."""

        if self._session is None:
            # Nothing to clean up.
            return

        try:
            await self._exit_stack.aclose()
        finally:
            self._session = None


async def discover_tools(config: MergedConfig) -> List[ToolDescriptor]:
    """Discover tools from all servers defined in the merged configuration.

    Args:
        config: Merged configuration containing all known servers.

    Returns:
        A list of :class:`ToolDescriptor` instances across all servers.
    """

    descriptors: List[ToolDescriptor] = []

    async def _load_for_server(server_config: ServerConfig) -> None:
        client = McpServerClient(server_config)
        try:
            await client.initialize()
            server_tools = await client.list_tools()
            descriptors.extend(server_tools)
        finally:
            await client.cleanup()

    await asyncio.gather(
        *(_load_for_server(server) for server in config.servers.values())
    )
    return descriptors
