"""
Architecture visualization models.
"""
from typing import Optional
from pydantic import BaseModel


class ArchitectureNode(BaseModel):
    """Represents a component in the architecture."""
    id: str
    type: str  # router, service, repository, agent, external
    name: str
    layer: str  # api, service, repository, agent, external
    file_path: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict] = None


class ArchitectureEdge(BaseModel):
    """Represents a dependency/connection between components."""
    source: str
    target: str
    type: str  # uses, calls, integrates
    label: Optional[str] = None


class ArchitectureGroup(BaseModel):
    """Groups nodes by layer for visual organization."""
    id: str
    name: str
    layer: str
    color: Optional[str] = None


class ArchitectureStats(BaseModel):
    """Statistics about the architecture."""
    routers: int
    services: int
    repositories: int
    agents: int
    external: int


class ArchitectureMetadata(BaseModel):
    """Metadata about the architecture response."""
    stats: ArchitectureStats


class ArchitectureResponse(BaseModel):
    """Complete architecture data for visualization."""
    nodes: list[ArchitectureNode]
    edges: list[ArchitectureEdge]
    groups: list[ArchitectureGroup]
    metadata: ArchitectureMetadata
