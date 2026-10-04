# Dockerfile for Android-MicroServer MCP Dev Agent
# Compatible with Glama introspection checks and containerized MCP clients
FROM python:3.11-slim

WORKDIR /app

# Copy MCP server implementation and schemas
COPY mcp/ /app/mcp/

# Ensure unbuffered UTF-8 output for JSON-RPC stdio
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

ENTRYPOINT ["python", "mcp/server.py"]
