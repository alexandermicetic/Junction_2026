"""Minimal async client for Claude's Messages API tool-use responses."""

import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_API_VERSION = "2026-10-21"


class ClaudeClient:
    """Call Claude with a forced structured tool response."""

    def __init__(self) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.api_version = os.getenv("ANTHROPIC_API_VERSION", DEFAULT_API_VERSION)
        self.workspace_id = os.getenv("ANTHROPIC_WORKSPACE_ID", "")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY must be configured in backend/.env")

    async def call_tool(self, *, system: str, prompt: str, tool: dict[str, Any]) -> dict[str, Any]:
        """Return the validated-by-schema input for the named forced tool call."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "anthropic-version": self.api_version,
            "content-type": "application/json",
        }
        if self.workspace_id:
            headers["anthropic-workspace-id"] = self.workspace_id

        payload = {
            "model": self.model,
            "max_tokens": 700,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool["name"], "disable_parallel_tool_use": True},
        }
        async with httpx.AsyncClient(timeout=35.0) as client:
            response = await client.post(ANTHROPIC_MESSAGES_URL, json=payload, headers=headers)
            response.raise_for_status()
        data = response.json()
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == tool["name"]:
                tool_input = block.get("input")
                if isinstance(tool_input, dict):
                    return tool_input
        raise ValueError("Claude returned no structured purchase decision")
