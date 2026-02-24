"""
Configuration manager for Agent-mem system.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import yaml


class ConfigManager:
    """Manages configuration for Agent-mem system."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize ConfigManager.

        Args:
            config_path: Path to configuration file. If None, uses defaults.
        """
        self.config_path = Path(config_path) if config_path else None
        self.config: Dict[str, Any] = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file or use defaults."""
        if self.config_path and self.config_path.exists():
            return self._load_from_file(self.config_path)
        else:
            return self._get_default_config()

    def _load_from_file(self, filepath: Path) -> Dict[str, Any]:
        """Load configuration from file."""
        suffix = filepath.suffix.lower()

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                if suffix == '.json':
                    return json.load(f)
                elif suffix in ['.yaml', '.yml']:
                    return yaml.safe_load(f)
                else:
                    raise ValueError(f"Unsupported config file format: {suffix}")
        except Exception as e:
            print(f"Warning: Failed to load config from {filepath}: {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            "system": {
                "name": "Agent-mem",
                "version": "0.1.0",
                "description": "Work-Experience Memory module for SWE-agent",
            },
            "storage": {
                "graph_store_dir": os.getenv("AGENT_MEM_STORAGE_DIR", "./agent_mem_data"),
                "evidence_dir": os.getenv("AGENT_MEM_EVIDENCE_DIR", "./agent_mem_evidence"),
                "persistence_interval": 60,  # seconds
                "auto_save": True,
            },
            "embeddings": {
                "dimension": 384,
                "model": "random",  # "random", "sentence-transformers", "openai"
                "model_name": "all-MiniLM-L6-v2",  # if using sentence-transformers
                "cache_dir": "./embedding_cache",
                "batch_size": 32,
            },
            "retrieval": {
                "max_planning_subgraphs": 3,
                "max_repair_subgraphs": 5,
                "similarity_threshold": 0.7,
                "embedding_view_weights": {
                    "emb_task_sem": 0.4,
                    "emb_file_scope": 0.2,
                    "emb_error_sig": 0.3,
                    "emb_intent": 0.1,
                },
            },
            "processing": {
                "enable_error_handler": True,
                "enable_rca": True,
                "max_suggestions": 3,
            },
            "beliefs": {
                "min_support_for_preference": 10,
                "min_uplift_for_preference": 0.1,
                "min_confidence_for_preference": 0.7,
                "min_support_for_constraint": 50,
                "min_uplift_for_constraint": 0.3,
                "min_confidence_for_constraint": 0.9,
                "forgetting_age_days": 30,
                "forgetting_access_threshold": 5,
            },
            "logging": {
                "level": "INFO",
                "file": os.getenv("AGENT_MEM_LOG_FILE", "./agent_mem.log"),
                "max_size_mb": 10,
                "backup_count": 5,
            },
            "integration": {
                "sweagent": {
                    "tool_a_enabled": True,
                    "tool_b_enabled": True,
                    "timeout_sec": 2.0,
                    "max_response_size": 10000,
                },
                "web": {
                    "enabled": False,
                    "host": "localhost",
                    "port": 8080,
                },
            },
            "performance": {
                "max_concurrent_queries": 10,
                "cache_size": 1000,
                "cache_ttl_seconds": 300,
            },
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-separated key."""
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value by dot-separated key."""
        keys = key.split('.')
        config = self.config

        # Navigate to the parent dict
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        # Set the value
        config[keys[-1]] = value

    def save(self, filepath: Optional[str] = None) -> bool:
        """Save configuration to file."""
        save_path = Path(filepath) if filepath else self.config_path
        if not save_path:
            return False

        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)

            suffix = save_path.suffix.lower()
            with open(save_path, 'w', encoding='utf-8') as f:
                if suffix == '.json':
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                elif suffix in ['.yaml', '.yml']:
                    yaml.dump(self.config, f, default_flow_style=False)
                else:
                    # Default to JSON
                    json.dump(self.config, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            print(f"Error saving config to {save_path}: {e}")
            return False

    def update_from_env(self) -> None:
        """Update configuration from environment variables."""
        env_mappings = {
            "AGENT_MEM_STORAGE_DIR": "storage.graph_store_dir",
            "AGENT_MEM_EVIDENCE_DIR": "storage.evidence_dir",
            "AGENT_MEM_LOG_LEVEL": "logging.level",
            "AGENT_MEM_LOG_FILE": "logging.file",
            "AGENT_MEM_EMBEDDING_MODEL": "embeddings.model",
            "AGENT_MEM_EMBEDDING_MODEL_NAME": "embeddings.model_name",
            "AGENT_MEM_EMBEDDING_DIMENSION": "embeddings.dimension",
            "AGENT_MEM_MAX_SUBGRAPHS": "retrieval.max_planning_subgraphs",
            "AGENT_MEM_TIMEOUT_SEC": "integration.sweagent.timeout_sec",
        }

        for env_var, config_key in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                if config_key in {"embeddings.dimension", "retrieval.max_planning_subgraphs"}:
                    try:
                        value = int(value)
                    except ValueError:
                        continue
                elif config_key == "integration.sweagent.timeout_sec":
                    try:
                        value = float(value)
                    except ValueError:
                        continue
                self.set(config_key, value)

    def validate(self) -> Dict[str, Any]:
        """Validate configuration and return validation results."""
        issues = []

        # Check storage directories
        storage_dir = self.get("storage.graph_store_dir")
        if storage_dir:
            try:
                Path(storage_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                issues.append(f"Cannot create storage directory {storage_dir}: {e}")

        # Check embedding configuration
        embedding_model = self.get("embeddings.model")
        if embedding_model not in ["random", "sentence-transformers", "openai"]:
            issues.append(f"Unsupported embedding model: {embedding_model}")

        # Check retrieval thresholds
        similarity_threshold = self.get("retrieval.similarity_threshold")
        if not (0.0 <= similarity_threshold <= 1.0):
            issues.append(f"Invalid similarity threshold: {similarity_threshold}")

        # Check belief thresholds
        min_support = self.get("beliefs.min_support_for_preference")
        if min_support < 1:
            issues.append(f"min_support_for_preference must be >= 1, got {min_support}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "config_summary": {
                "storage_dir": self.get("storage.graph_store_dir"),
                "embedding_model": self.get("embeddings.model"),
                "max_subgraphs": self.get("retrieval.max_planning_subgraphs"),
                "auto_save": self.get("storage.auto_save"),
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary."""
        return self.config.copy()

    def get_config(self) -> Dict[str, Any]:
        """Compatibility helper: return full configuration."""
        return self.to_dict()

    def __str__(self) -> str:
        """String representation of configuration."""
        return json.dumps(self.config, indent=2, ensure_ascii=False)
