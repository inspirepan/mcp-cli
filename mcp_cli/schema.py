"""Helpers for mapping JSON Schemas to CLI-friendly option specifications.

This module focuses on *simple* schemas where the tool input is an object
made up of scalar fields. More complex schemas should continue to use the
JSON-based argument passing mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PropertySpec:
    """Specification for exposing a JSON Schema property as a CLI option.

    Attributes:
        name: Original JSON property name in the schema.
        param_name: Parameter name used by Click and passed to the handler.
        cli_flag: The long option flag (for example "--file_path").
        type: Logical type of the property: "string", "integer", "number", or "boolean".
        required: Whether the property is required at the schema level.
        choices: Optional list of allowed values (from an ``enum`` definition).
        description: Optional human-readable description of the property.
    """

    name: str
    param_name: str
    cli_flag: str
    type: str
    required: bool
    choices: list[str] | None = None
    description: str | None = None


_RESERVED_PARAM_NAMES: set[str] = {"json", "json_file", "json_stdin", "output"}


def build_property_specs(schema: dict[str, Any]) -> list[PropertySpec]:
    """Build CLI property specifications from a JSON Schema.

    Only simple object schemas are considered. For each eligible property a
    :class:`PropertySpec` is returned. Properties that are not recognized as
    simple scalars are ignored, so that callers can continue to rely on
    JSON-based argument passing for complex inputs.

    Args:
        schema: The JSON Schema describing the tool input.

    Returns:
        A list of :class:`PropertySpec` instances. The list may be empty when
        the schema is not suitable for automatic flag mapping.
    """

    if not isinstance(schema, dict):
        return []

    if schema.get("type") != "object":
        return []

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []

    required_props = schema.get("required", [])
    if not isinstance(required_props, list):
        required_props = []

    specs: list[PropertySpec] = []

    for raw_name, prop_schema in properties.items():
        if not isinstance(raw_name, str):
            continue
        if raw_name in _RESERVED_PARAM_NAMES:
            # Avoid collisions with internal option names.
            continue
        if not isinstance(prop_schema, dict):
            continue

        prop_type_value = prop_schema.get("type")
        if isinstance(prop_type_value, list):
            # If multiple types are allowed, we only handle the simple case
            # where exactly one of the supported scalar types is present.
            scalar_types = {"string", "integer", "number", "boolean"}
            candidates = [t for t in prop_type_value if t in scalar_types]
            if len(candidates) != 1:
                continue
            prop_type = candidates[0]
        elif isinstance(prop_type_value, str):
            prop_type = prop_type_value
        else:
            continue

        if prop_type not in {"string", "integer", "number", "boolean"}:
            # Arrays and objects are currently left to JSON-based arguments.
            continue

        description = prop_schema.get("description")
        if not isinstance(description, str):
            description = None

        enum_values = prop_schema.get("enum")
        choices: list[str] | None = None
        if isinstance(enum_values, list) and enum_values:
            # Only keep simple string enums; other types are not mapped.
            if all(isinstance(item, str) for item in enum_values):
                choices = list(enum_values)

        is_required = raw_name in required_props

        param_name = raw_name
        cli_flag = f"--{raw_name}"

        specs.append(
            PropertySpec(
                name=raw_name,
                param_name=param_name,
                cli_flag=cli_flag,
                type=prop_type,
                required=is_required,
                choices=choices,
                description=description,
            )
        )

    return specs
