"""Shared response and error contracts for the purpose-specific MCP services."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mcp.server.mcpserver.exceptions import ToolError

ErrorCode = Literal[
    "invalid_input",
    "not_found",
    "conflict",
    "service_unavailable",
    "internal_error",
]


class ServiceError(BaseModel):
    """A safe, machine-readable service error returned by an MCP tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    message: str = Field(min_length=1)


def tool_error(code: ErrorCode, message: str) -> ToolError:
    """Format an MCP failure using the shared JSON error envelope."""

    return ToolError(
        json.dumps(
            {"error": ServiceError(code=code, message=message).model_dump()},
            separators=(",", ":"),
        )
    )
