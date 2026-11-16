"""Ferramentas do agente."""

from formiga.agent.tools.deepsearch import DeepSearchTool
from formiga.agent.tools.files import EditTool, LsTool, ReadTool, WriteTool
from formiga.agent.tools.shell import BashTool
from formiga.agent.tools.web import WebFetchTool, WebSearchTool

ALL_TOOLS = (
    LsTool,
    ReadTool,
    WriteTool,
    EditTool,
    BashTool,
    WebSearchTool,
    WebFetchTool,
    DeepSearchTool,
)
FILE_TOOLS = (LsTool, ReadTool, WriteTool, EditTool)
WEB_TOOLS = (WebSearchTool, WebFetchTool)

__all__ = [
    "BashTool",
    "DeepSearchTool",
    "EditTool",
    "LsTool",
    "ReadTool",
    "WebFetchTool",
    "WebSearchTool",
    "WriteTool",
    "ALL_TOOLS",
    "FILE_TOOLS",
    "WEB_TOOLS",
]
