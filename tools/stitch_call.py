"""Thin JSON-RPC client for the project's Stitch MCP server (reads ./.mcp.json).

The in-session MCP connection was established before this branch's .mcp.json was
checked out, so it cannot pick the credential up; this lets the same server be
driven directly. Usage: python3 tools/stitch_call.py <tool> '<json args>'
"""
import json, subprocess, sys, pathlib

cfg = json.loads(pathlib.Path(".mcp.json").read_text())["mcpServers"]["stitch"]
payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": sys.argv[1], "arguments": json.loads(sys.argv[2])}}
r = subprocess.run(
    ["curl", "-sS", "--max-time", "900", "-X", "POST", cfg["url"],
     "-H", "X-Goog-Api-Key: " + cfg["headers"]["X-Goog-Api-Key"],
     "-H", "Content-Type: application/json",
     "-H", "Accept: application/json, text/event-stream",
     "-d", json.dumps(payload)], capture_output=True, text=True)
print(r.stdout[:40000] or r.stderr[:2000])
