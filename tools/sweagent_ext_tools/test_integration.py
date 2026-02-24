#!/usr/bin/env python
"""
Integration test for Agent-mem MVP.
Tests plan_generated and action_error event handling.
"""
import sys
import os
import json
import tempfile
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import integration components
from agent_mem.integration.sweagent_adapter import SWEAgentAdapter
from agent_mem.processing.action_logger import ActionLogger
from agent_mem.processing.error_handler import ErrorHandler
from agent_mem.processing.kg_writer import EmbeddingGenerator
from agent_mem.retrieval.memory_agent import MemoryAgent
from agent_mem.storage.graph_store import GraphStore

def test_sweagent_adapter():
    """Test SWE-agent adapter integration."""
    print("Testing SWE-agent adapter...")

    # Create adapter with temporary storage
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = SWEAgentAdapter(storage_dir=tmpdir, evidence_dir=tmpdir)

        # Test plan_generated hook
        plan_data = {
            "agent": "integration-test",
            "thought": "Need a safe fix workflow",
            "action": "1. Read the file\n2. Fix the bug\n3. Run tests",
        }

        result = adapter.handle_plan_generated(plan_data)
        print(f"  plan_generated result: {result}")
        assert result is not None
        print("✓ plan_generated hook test passed")

        # Test action_error hook
        error_data = {
            "agent": "integration-test",
            "thought": "The file read failed",
            "action": "cat main.py",
            "error_type": "file_not_found",
            "error_message": "File not found: main.py",
            "context": {
                "working_dir": "/tmp/test",
                "files": ["main.py", "test.py"]
            }
        }

        result = adapter.handle_action_error(error_data)
        print(f"  action_error result: {result}")
        assert result is not None
        print("✓ action_error hook test passed")

        # Cross-process continuity simulation:
        # New adapter instance should resume same task context and create fail-retry edge.
        adapter2 = SWEAgentAdapter(storage_dir=tmpdir, evidence_dir=tmpdir)
        result2 = adapter2.handle_action_error(error_data)
        assert result2 is not None
        assert result2.get("task_id") == result.get("task_id")

        subgraph = adapter2.graph_store.observation_kg.get_task_subgraph(result2["task_id"])
        assert subgraph is not None
        assert len(subgraph.action_nodes) >= 2
        assert len(subgraph.get_failure_retry_chains()) >= 1
        print("✓ cross-process continuity test passed")

        done = adapter2.handle_run_done(
            {
                "agent": "integration-test",
                "instance_id": "integration-test",
                "event": "run_done",
                "exit_status": "submitted",
                "has_submission": True,
            }
        )
        assert done.get("event_handled") == "run_done"
        assert done.get("cleared") is True
        assert done.get("belief_update", {}).get("new_beliefs_created", 0) >= 1
        print("✓ run_done context cleanup test passed")

        search_result = adapter2.search_experience("fix file read failure", max_results=3)
        assert search_result.get("total_found", 0) >= 1
        assert isinstance(search_result.get("recommendations", []), list)
        print("✓ search_experience formal output test passed")

def test_action_logger():
    """Test action logger functionality."""
    print("\nTesting Action Logger...")

    with tempfile.TemporaryDirectory() as tmpdir:
        graph_store = GraphStore(storage_dir=tmpdir)
        logger = ActionLogger(graph_store, evidence_dir=tmpdir)
        logger.start_task("test_task_002")

        # Test logging an action
        from agent_mem.core.problem_file import ActionType, Outcome
        problem_file = logger.log_action(
            action_type=ActionType.CODE_EDIT,
            intent_text="Add missing import",
            inputs={"target": "main.py"},
            tool_calls=[{"tool": "editor", "action": "insert"}],
            outcome=Outcome.SUCCESS,
            stdout="File modified successfully",
            diff_content="+import os",
        )
        assert problem_file is not None
        assert problem_file.task_id == "test_task_002"
        print("✓ Action logging test passed")

def test_error_handler():
    """Test error handler functionality."""
    print("\nTesting Error Handler...")

    with tempfile.TemporaryDirectory() as tmpdir:
        graph_store = GraphStore(storage_dir=tmpdir)
        from agent_mem.core.observation_kg import ObservationKG
        observation_kg = ObservationKG()
        handler = ErrorHandler(graph_store, observation_kg)

        # Test error analysis
        error_context = {
            "task_id": "test_task_003",
            "error_type": "ImportError",
            "error_message": "No module named 'missing_module'",
            "action_type": "import",
            "file_path": "/tmp/test/main.py",
            "line_number": 5
        }

        suggestions = handler.analyze_error(error_context)
        print(f"  Error suggestions: {suggestions}")
        assert isinstance(suggestions, list)
        print("✓ Error analysis test passed")

def test_memory_agent():
    """Test memory agent functionality."""
    print("\nTesting Memory Agent...")

    with tempfile.TemporaryDirectory() as tmpdir:
        graph_store = GraphStore(storage_dir=tmpdir)
        agent = MemoryAgent(graph_store)

        # Test query rewriting
        query = "How to fix import errors in Python?"
        rewritten = agent.query_rewriting(query)
        print(f"  Original query: {query}")
        print(f"  Rewritten query: {rewritten}")
        assert rewritten is not None
        print("✓ Query rewriting test passed")

        # Test experience distillation
        experiences = [
            {
                "task_id": "exp_001",
                "description": "Fixed import error by adding missing package",
                "solution": "pip install missing-package"
            }
        ]

        distilled = agent.experience_distillation(experiences)
        print(f"  Distilled experience: {distilled}")
        assert distilled is not None
        print("✓ Experience distillation test passed")

def test_graph_store():
    """Test graph store functionality."""
    print("\nTesting Graph Store...")

    # Create temporary directory for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        store = GraphStore(storage_dir=tmpdir)

        # Test basic operations
        print(f"  Storage dir: {store.storage_dir}")
        assert store.observation_kg is not None
        assert store.belief_graph is not None
        print("✓ Graph store initialization test passed")

        # Test saving observation KG
        from agent_mem.core.observation_kg import TaskSubgraph
        from agent_mem.core.problem_file import ProblemFile, ActionType

        subgraph = TaskSubgraph(task_id="test_task")
        pf = ProblemFile(task_id="test_task", action_type=ActionType.TOOL_CALL)
        subgraph.add_action(pf)
        store.observation_kg.add_task_subgraph(subgraph)

        # Save to file
        if store.storage_dir:
            kg_file = store.storage_dir / "observation_kg.json"
            store.observation_kg.save_to_file(str(kg_file))
            assert kg_file.exists()
            print("✓ Observation KG save test passed")

def test_embedding_generator_configuration():
    """Test embedding generator provider selection and fallback."""
    print("\nTesting Embedding Generator...")

    random_gen = EmbeddingGenerator(model="random", embedding_dim=32)
    random_vec = random_gen.generate_intent_embedding("fix parser bug")
    assert len(random_vec) == 32
    assert random_gen.provider == "random"

    st_gen = EmbeddingGenerator(model="sentence-transformers", embedding_dim=32)
    st_vec = st_gen.generate_intent_embedding("fix parser bug")
    assert len(st_vec) > 0
    assert st_gen.provider in {"sentence-transformers", "random"}
    print("✓ Embedding generator config test passed")

def main():
    """Run all integration tests."""
    print("Running Agent-mem MVP integration tests...")
    print("="*60)

    tests_passed = 0
    tests_failed = 0

    try:
        test_sweagent_adapter()
        tests_passed += 1
    except Exception as e:
        print(f"✗ SWE-agent adapter test failed: {e}")
        tests_failed += 1

    try:
        test_action_logger()
        tests_passed += 1
    except Exception as e:
        print(f"✗ Action logger test failed: {e}")
        tests_failed += 1

    try:
        test_error_handler()
        tests_passed += 1
    except Exception as e:
        print(f"✗ Error handler test failed: {e}")
        tests_failed += 1

    try:
        test_memory_agent()
        tests_passed += 1
    except Exception as e:
        print(f"✗ Memory agent test failed: {e}")
        tests_failed += 1

    try:
        test_graph_store()
        tests_passed += 1
    except Exception as e:
        print(f"✗ Graph store test failed: {e}")
        tests_failed += 1

    try:
        test_embedding_generator_configuration()
        tests_passed += 1
    except Exception as e:
        print(f"✗ Embedding generator test failed: {e}")
        tests_failed += 1

    print("\n" + "="*60)
    print(f"Integration Test Summary:")
    print(f"  Passed: {tests_passed}")
    print(f"  Failed: {tests_failed}")
    print(f"  Total:  {tests_passed + tests_failed}")

    return tests_failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
