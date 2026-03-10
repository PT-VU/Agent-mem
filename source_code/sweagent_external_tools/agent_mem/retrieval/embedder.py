"""
多视角Embedding生成器

基于Agent-mem架构文档第4.2节：
- emb_task_sem: 任务语义摘要向量
- emb_file_scope: 文件范围/模块向量
- emb_error_sig: 报错签名向量
- emb_tool_output: 工具输出摘要向量
- emb_diff_summary: diff摘要向量
- emb_intent: intent_text向量

MVP使用sentence-transformers，后续可扩展为专用模型。
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import hashlib
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print("Warning: sentence-transformers not available. Using dummy embeddings.")


class EmbeddingType(Enum):
    """Embedding类型枚举"""
    TASK_SEM = "task_sem"          # 任务语义摘要
    FILE_SCOPE = "file_scope"      # 文件范围/模块
    ERROR_SIG = "error_sig"        # 报错签名
    TOOL_OUTPUT = "tool_output"    # 工具输出摘要
    DIFF_SUMMARY = "diff_summary"  # diff摘要
    INTENT = "intent"              # 意图文本


class MultiViewEmbedder:
    """
    多视角Embedding生成器

    为ProblemFile生成多种视角的embedding，支持分层检索。
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", cache_size: int = 1000):
        """
        初始化Embedder

        Args:
            model_name: sentence-transformers模型名称
            cache_size: embedding缓存大小
        """
        self.model_name = model_name
        self.cache_size = cache_size
        self.embedding_cache: Dict[str, List[float]] = {}
        self.model = None

        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.model = SentenceTransformer(model_name)
                print(f"Loaded sentence-transformers model: {model_name}")
            except Exception as e:
                print(f"Failed to load model {model_name}: {e}")
                self.model = None
        else:
            self.model = None

    def embed_text(self, text: str) -> List[float]:
        """
        生成文本embedding

        Args:
            text: 输入文本

        Returns:
            embedding向量
        """
        if not text:
            return self._dummy_embedding()

        # 检查缓存
        cache_key = self._get_cache_key(text)
        if cache_key in self.embedding_cache:
            return self.embedding_cache[cache_key]

        # 生成embedding
        if self.model:
            try:
                embedding = self.model.encode(text, convert_to_numpy=True).tolist()
            except Exception as e:
                print(f"Embedding generation failed: {e}")
                embedding = self._dummy_embedding()
        else:
            embedding = self._dummy_embedding()

        # 更新缓存
        self._update_cache(cache_key, embedding)

        return embedding

    def generate_problem_file_embeddings(self, problem_file_data: Dict[str, Any]) -> Dict[str, List[float]]:
        """
        为ProblemFile生成多视角embedding

        Args:
            problem_file_data: ProblemFile数据字典

        Returns:
            各视角embedding字典
        """
        embeddings = {}

        # 1. 任务语义embedding (基于intent_text和tool_calls)
        task_sem_text = self._extract_task_semantic_text(problem_file_data)
        embeddings[EmbeddingType.TASK_SEM.value] = self.embed_text(task_sem_text)

        # 2. 文件范围embedding (基于touched_files)
        file_scope_text = self._extract_file_scope_text(problem_file_data)
        embeddings[EmbeddingType.FILE_SCOPE.value] = self.embed_text(file_scope_text)

        # 3. 错误签名embedding (如果有错误)
        error_sig_text = self._extract_error_signature_text(problem_file_data)
        if error_sig_text:
            embeddings[EmbeddingType.ERROR_SIG.value] = self.embed_text(error_sig_text)

        # 4. 工具输出embedding (基于stdout/stderr摘要)
        tool_output_text = self._extract_tool_output_text(problem_file_data)
        if tool_output_text:
            embeddings[EmbeddingType.TOOL_OUTPUT.value] = self.embed_text(tool_output_text)

        # 5. diff摘要embedding (如果有diff)
        diff_summary_text = self._extract_diff_summary_text(problem_file_data)
        if diff_summary_text:
            embeddings[EmbeddingType.DIFF_SUMMARY.value] = self.embed_text(diff_summary_text)

        # 6. 意图embedding (基于intent_text)
        intent_text = problem_file_data.get("intent_text", "")
        if intent_text:
            embeddings[EmbeddingType.INTENT.value] = self.embed_text(intent_text)

        return embeddings

    def _extract_task_semantic_text(self, problem_file_data: Dict[str, Any]) -> str:
        """提取任务语义文本"""
        intent_text = problem_file_data.get("intent_text", "")
        tool_calls = problem_file_data.get("tool_calls", [])

        # 提取工具调用信息
        tool_info = []
        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                tool_name = tool_call.get("tool", "")
                args = tool_call.get("args", {})
                tool_info.append(f"{tool_name}: {args}")

        return f"Intent: {intent_text}. Tools: {'; '.join(tool_info)}"

    def _extract_file_scope_text(self, problem_file_data: Dict[str, Any]) -> str:
        """提取文件范围文本"""
        touched_files = problem_file_data.get("touched_files", [])
        if not touched_files:
            return ""

        # 提取文件扩展名统计
        extensions = {}
        for file_path in touched_files:
            if '.' in file_path:
                ext = file_path.split('.')[-1]
                extensions[ext] = extensions.get(ext, 0) + 1

        ext_summary = ", ".join([f"{ext}:{count}" for ext, count in extensions.items()])
        return f"Files: {', '.join(touched_files[:5])}. Extensions: {ext_summary}"

    def _extract_error_signature_text(self, problem_file_data: Dict[str, Any]) -> str:
        """提取错误签名文本"""
        failure_signature = problem_file_data.get("failure_signature")
        if not failure_signature:
            return ""

        error_type = failure_signature.get("error_type", "")
        key_tokens = failure_signature.get("key_tokens", [])
        error_context = failure_signature.get("context", "")

        tokens_text = ", ".join(key_tokens[:10])
        return f"Error type: {error_type}. Tokens: {tokens_text}. Context: {error_context[:200]}"

    def _extract_tool_output_text(self, problem_file_data: Dict[str, Any]) -> str:
        """提取工具输出文本"""
        # 这里简化处理，实际应从evidence指针加载
        # MVP版本使用占位符
        outcome = problem_file_data.get("outcome", "")
        return f"Outcome: {outcome}"

    def _extract_diff_summary_text(self, problem_file_data: Dict[str, Any]) -> str:
        """提取diff摘要文本"""
        # 这里简化处理，实际应从diff证据指针加载
        # MVP版本返回空字符串
        return ""

    def _get_cache_key(self, text: str) -> str:
        """生成缓存键"""
        return hashlib.md5(text.encode()).hexdigest()

    def _update_cache(self, key: str, embedding: List[float]) -> None:
        """更新缓存"""
        if len(self.embedding_cache) >= self.cache_size:
            # 简单LRU：移除第一个键
            first_key = next(iter(self.embedding_cache))
            del self.embedding_cache[first_key]

        self.embedding_cache[key] = embedding

    def _dummy_embedding(self, dimension: int = 384) -> List[float]:
        """生成虚拟embedding（用于测试）"""
        return [0.0] * dimension

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "model_name": self.model_name,
            "cache_size": len(self.embedding_cache),
            "max_cache_size": self.cache_size,
            "model_available": self.model is not None
        }


class EmbeddingManager:
    """
    Embedding管理器

    管理多视角embedding的生成、存储和检索。
    """

    def __init__(self, storage_backend=None, embedder: MultiViewEmbedder = None):
        """
        初始化Embedding管理器

        Args:
            storage_backend: 存储后端
            embedder: Embedder实例
        """
        self.storage_backend = storage_backend
        self.embedder = embedder or MultiViewEmbedder()

    def generate_and_store_embeddings(self, problem_file_data: Dict[str, Any]) -> Dict[str, List[float]]:
        """
        生成并存储embedding

        Args:
            problem_file_data: ProblemFile数据

        Returns:
            生成的embedding字典
        """
        # 生成embedding
        embeddings = self.embedder.generate_problem_file_embeddings(problem_file_data)

        # 存储embedding
        if self.storage_backend:
            problem_file_id = problem_file_data.get("action_id")
            if problem_file_id:
                for emb_type, emb_vector in embeddings.items():
                    self.storage_backend.save_embedding(
                        problem_file_id,
                        emb_type,
                        emb_vector
                    )

        return embeddings

    def search_similar(self,
                      query_text: str,
                      embedding_type: str,
                      limit: int = 10) -> List[Dict[str, Any]]:
        """
        搜索相似的embedding

        Args:
            query_text: 查询文本
            embedding_type: embedding类型
            limit: 返回结果数量

        Returns:
            相似结果列表
        """
        # 生成查询embedding
        query_embedding = self.embedder.embed_text(query_text)

        # 搜索相似
        if self.storage_backend:
            return self.storage_backend.search_similar(
                query_embedding,
                embedding_type,
                limit
            )
        else:
            # 如果没有存储后端，返回空结果
            return []

    def get_embeddings_for_problem_file(self, problem_file_id: str) -> Dict[str, List[float]]:
        """
        获取ProblemFile的所有embedding

        Args:
            problem_file_id: ProblemFile ID

        Returns:
            embedding字典
        """
        if not self.storage_backend:
            return {}

        embeddings = {}
        for emb_type in EmbeddingType:
            emb_vector = self.storage_backend.load_embedding(
                problem_file_id,
                emb_type.value
            )
            if emb_vector:
                embeddings[emb_type.value] = emb_vector

        return embeddings