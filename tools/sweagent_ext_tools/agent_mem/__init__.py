"""
Agent-mem: Work-Experience Memory module for SWE-agent

A training-free memory system that provides retrievable, structured, and verifiable
work experience for long-horizon software engineering tasks.
"""

from .core.problem_file import ProblemFile
from .core.observation_kg import ObservationKG, EdgeType
from .core.belief_graph import BeliefGraph
from .storage.graph_store import GraphStore
from .processing.action_logger import ActionLogger
from .processing.kg_writer import KGWriter
from .retrieval.memory_agent import MemoryAgent
from .integration.sweagent_adapter import SWEAgentAdapter
from .config.config_manager import ConfigManager

__version__ = "0.1.0"
__all__ = [
    "ProblemFile",
    "ObservationKG",
    "EdgeType",
    "BeliefGraph",
    "GraphStore",
    "ActionLogger",
    "KGWriter",
    "MemoryAgent",
    "SWEAgentAdapter",
    "ConfigManager",
]