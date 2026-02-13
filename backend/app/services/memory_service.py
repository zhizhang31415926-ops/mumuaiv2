"""向量记忆服务 - 基于ChromaDB实现长期记忆和语义检索"""
import chromadb
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Optional
import json
from datetime import datetime
import httpx
from app.logger import get_logger
import os
import hashlib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings as app_settings
from app.models.settings import Settings

logger = get_logger(__name__)

# 配置模型缓存目录
# 优先使用 backend/embedding 目录（打包后的实际位置）
import sys
from pathlib import Path

if 'SENTENCE_TRANSFORMERS_HOME' not in os.environ:
    # 根据运行环境确定模型目录
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后 - 需要检查多个可能的位置
        exe_dir = Path(sys.executable).parent
        
        # 检查顺序：
        # 1. _MEIPASS/backend/embedding (临时解压目录)
        # 2. exe同级/_internal/backend/embedding
        # 3. exe同级/backend/embedding
        possible_paths = []
        
        if hasattr(sys, '_MEIPASS'):
            possible_paths.append(Path(sys._MEIPASS) / 'backend' / 'embedding')
        
        possible_paths.extend([
            exe_dir / '_internal' / 'backend' / 'embedding',
            exe_dir / 'backend' / 'embedding',
            exe_dir / '_internal' / 'embedding',
            exe_dir / 'embedding'
        ])
        
        model_dir = None
        for path in possible_paths:
            if path.exists():
                model_dir = path
                logger.info(f"🔧 找到打包环境模型目录: {model_dir}")
                break
        
        if model_dir:
            os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(model_dir)
        else:
            # 最后降级方案
            fallback_dir = exe_dir / 'embedding'
            os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(fallback_dir)
            logger.warning(f"⚠️ 未找到预打包模型，使用降级目录: {fallback_dir}")
            logger.warning(f"   检查过的路径: {[str(p) for p in possible_paths]}")
    else:
        # 开发模式，从当前文件位置向上找到项目根目录
        base_dir = Path(__file__).parent.parent.parent
        model_dir = base_dir / 'backend' / 'embedding'
        if model_dir.exists():
            os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(model_dir)
            logger.info(f"🔧 设置开发环境模型目录: {model_dir}")
        else:
            # 降级到项目根目录的 embedding
            fallback_dir = base_dir / 'embedding'
            os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(fallback_dir)
            logger.info(f"🔧 使用降级模型目录: {fallback_dir}")


class MemoryService:
    """向量记忆管理服务 - 实现语义检索和长期记忆"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化ChromaDB和Embedding模型"""
        if self._initialized:
            return
            
        try:
            # 确保数据目录存在
            chroma_dir = "data/chroma_db"
            os.makedirs(chroma_dir, exist_ok=True)
            
            # 初始化ChromaDB客户端(使用新API - PersistentClient)
            self.client = chromadb.PersistentClient(path=chroma_dir)

            # Embedding 默认配置
            default_embedding_model = app_settings.default_embedding_model or ""
            self.local_model_name = (
                default_embedding_model
                if default_embedding_model.startswith("sentence-transformers/")
                else "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            )
            self.default_api_model_name = (
                default_embedding_model
                if default_embedding_model and not default_embedding_model.startswith("sentence-transformers/")
                else "text-embedding-3-small"
            )

            # API 模式下跳过启动期本地模型加载，避免首次启动被模型下载阻塞
            default_mode = str(app_settings.default_embedding_mode or "local").strip().lower()
            if default_mode == "api":
                self.embedding_model = None
                self._initialized = True
                logger.info("✅ MemoryService初始化成功（API模式，已跳过本地Embedding模型预加载）")
                logger.info(f"  - ChromaDB目录: {chroma_dir}")
                logger.info(f"  - 本地Embedding模型(按需加载): {self.local_model_name}")
                return
            
            # 初始化多语言embedding模型(支持中文)
            logger.info("🔄 正在加载Embedding模型...")
            
            # 使用环境变量中配置的模型目录
            model_cache_dir = os.environ.get('SENTENCE_TRANSFORMERS_HOME', 'embedding')
            os.makedirs(model_cache_dir, exist_ok=True)
            logger.info(f"📂 使用模型缓存目录: {os.path.abspath(model_cache_dir)}")
            
            # 调试信息：打印环境变量和路径
            logger.info(f"📂 当前工作目录: {os.getcwd()}")
            logger.info(f"📂 模型缓存目录: {os.path.abspath(model_cache_dir)}")
            logger.info(f"🔧 SENTENCE_TRANSFORMERS_HOME: {os.environ.get('SENTENCE_TRANSFORMERS_HOME', '未设置')}")
            logger.info(f"🔧 TRANSFORMERS_OFFLINE: {os.environ.get('TRANSFORMERS_OFFLINE', '未设置')}")
            logger.info(f"🔧 HF_HUB_OFFLINE: {os.environ.get('HF_HUB_OFFLINE', '未设置')}")
            
            # 检查模型目录内容
            abs_cache_dir = os.path.abspath(model_cache_dir)
            logger.info(f"📂 检查模型缓存目录: {abs_cache_dir}")
            
            if os.path.exists(abs_cache_dir):
                logger.info(f"📁 模型目录存在，检查内容...")
                try:
                    items = os.listdir(abs_cache_dir)
                    logger.info(f"📁 模型目录内容 ({len(items)} 项): {items}")
                    
                    # 检查是否有预期的模型文件夹
                    expected_model_dir = os.path.join(abs_cache_dir, 'models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2')
                    logger.info(f"🔍 检查预期路径: {expected_model_dir}")
                    
                    if os.path.exists(expected_model_dir):
                        logger.info(f"✅ 找到本地模型目录!")
                        # 检查快照目录
                        snapshots_dir = os.path.join(expected_model_dir, 'snapshots')
                        if os.path.exists(snapshots_dir):
                            snapshots = os.listdir(snapshots_dir)
                            logger.info(f"📁 模型快照 ({len(snapshots)} 个): {snapshots}")
                            # 检查是否有有效的快照
                            if snapshots:
                                logger.info(f"✅ 发现有效快照，可以使用离线模式")
                    else:
                        logger.warning(f"⚠️ 未找到本地模型目录")
                        logger.warning(f"   预期位置: {expected_model_dir}")
                except Exception as e:
                    logger.error(f"❌ 检查模型目录失败: {str(e)}")
                    import traceback
                    logger.error(f"   堆栈: {traceback.format_exc()}")
            else:
                logger.warning(f"⚠️ 模型目录不存在: {abs_cache_dir}")
            
            try:
                logger.info("🔄 尝试加载主模型: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
                
                # 使用绝对路径检查本地模型
                abs_cache_dir = os.path.abspath(model_cache_dir)
                local_model_path = os.path.join(
                    abs_cache_dir,
                    'models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2'
                )
                
                logger.info(f"🔍 检查本地模型路径: {local_model_path}")
                logger.info(f"🔍 路径存在检查: {os.path.exists(local_model_path)}")
                
                # 检查快照目录是否存在且有内容
                snapshots_dir = os.path.join(local_model_path, 'snapshots')
                has_valid_model = False
                if os.path.exists(snapshots_dir):
                    try:
                        snapshots = os.listdir(snapshots_dir)
                        if snapshots:
                            logger.info(f"✅ 发现本地模型快照: {snapshots}")
                            has_valid_model = True
                    except Exception as e:
                        logger.warning(f"⚠️ 检查快照失败: {e}")
                
                # 优先尝试从本地路径加载
                if has_valid_model:
                    logger.info(f"✅ 检测到完整本地模型，使用离线模式加载")
                    try:
                        self.embedding_model = SentenceTransformer(
                            'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                            cache_folder=abs_cache_dir,
                            device='cpu',
                            trust_remote_code=True,
                            local_files_only=True  # 强制使用本地文件
                        )
                        logger.info("✅ Embedding模型加载成功 (离线模式)")
                    except Exception as local_err:
                        logger.warning(f"⚠️ 离线模式加载失败: {str(local_err)}")
                        logger.info("🔄 尝试在线模式...")
                        raise local_err
                else:
                    logger.info("📥 本地模型不完整或不存在，将联网下载...")
                    logger.info(f"   下载后将保存到: {abs_cache_dir}")
                    self.embedding_model = SentenceTransformer(
                        'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                        cache_folder=abs_cache_dir,
                        device='cpu',
                        trust_remote_code=True,
                        local_files_only=False  # 允许联网下载
                    )
                    logger.info("✅ Embedding模型加载成功 (在线下载)")
            except Exception as e:
                logger.warning(f"⚠️ 无法加载多语言模型: {str(e)}")
                logger.error(f"❌ 详细错误: {repr(e)}")
                import traceback
                logger.error(f"❌ 错误堆栈:\n{traceback.format_exc()}")
                logger.info("🔄 尝试使用备用模型: sentence-transformers/all-MiniLM-L6-v2")
                try:
                    # 降级到更小的模型作为备选
                    self.embedding_model = SentenceTransformer(
                        'sentence-transformers/all-MiniLM-L6-v2',
                        cache_folder=model_cache_dir,
                        device='cpu',
                        trust_remote_code=False
                    )
                    logger.info("✅ 使用备用Embedding模型 (all-MiniLM-L6-v2)")
                except Exception as e2:
                    logger.error(f"❌ 所有模型加载失败: {str(e2)}")
                    logger.error(f"❌ 详细错误: {repr(e2)}")
                    import traceback
                    logger.error(f"❌ 错误堆栈:\n{traceback.format_exc()}")
                    logger.error("💡 模型首次使用需要联网下载（约420MB）")
                    logger.error("   或手动下载模型文件到 embedding 目录")
                    logger.error(f"💡 期望的模型目录结构:")
                    logger.error(f"   {os.path.abspath(model_cache_dir)}/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/")
                    raise RuntimeError("无法加载任何Embedding模型")
            
            self._initialized = True
            logger.info("✅ MemoryService初始化成功")
            logger.info(f"  - ChromaDB目录: {chroma_dir}")
            logger.info(f"  - 本地Embedding模型: {self.local_model_name}")
            
        except Exception as e:
            logger.error(f"❌ MemoryService初始化失败: {str(e)}")
            raise

    def _ensure_local_embedding_model(self) -> None:
        """按需加载本地Embedding模型（仅在使用local模式时触发）。"""
        if getattr(self, "embedding_model", None) is not None:
            return

        model_cache_dir = os.environ.get("SENTENCE_TRANSFORMERS_HOME", "embedding")
        os.makedirs(model_cache_dir, exist_ok=True)
        logger.info("🔄 按需加载本地Embedding模型...")

        try:
            self.embedding_model = SentenceTransformer(
                self.local_model_name,
                cache_folder=os.path.abspath(model_cache_dir),
                device="cpu",
                trust_remote_code=True,
                local_files_only=False,
            )
            logger.info("✅ 本地Embedding模型按需加载成功")
        except Exception as exc:
            logger.error(f"❌ 本地Embedding模型按需加载失败: {exc}")
            raise RuntimeError("无法加载本地Embedding模型，请检查网络或切换为API模式")
    
    async def _resolve_embedding_config(
        self,
        user_id: str,
        db: Optional[AsyncSession] = None,
        override: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """解析用户当前 Embedding 配置（支持本地/API模式）。"""
        config = {
            "embedding_mode": (app_settings.default_embedding_mode or "local"),
            "embedding_provider": (app_settings.default_embedding_provider or "openai"),
            "embedding_model": (app_settings.default_embedding_model or self.local_model_name),
            "embedding_api_key": (app_settings.default_embedding_api_key or ""),
            "embedding_api_base_url": (
                app_settings.default_embedding_api_base_url
                or "https://api.openai.com/v1"
            ),
        }

        if db is not None:
            try:
                result = await db.execute(select(Settings).where(Settings.user_id == user_id))
                user_settings = result.scalar_one_or_none()
                if user_settings:
                    config.update({
                        "embedding_mode": user_settings.embedding_mode or config["embedding_mode"],
                        "embedding_provider": user_settings.embedding_provider or config["embedding_provider"],
                        "embedding_model": user_settings.embedding_model or config["embedding_model"],
                        "embedding_api_key": user_settings.embedding_api_key or config["embedding_api_key"],
                        "embedding_api_base_url": user_settings.embedding_api_base_url or config["embedding_api_base_url"],
                    })
            except Exception as exc:
                logger.warning(f"⚠️ 读取用户Embedding配置失败，使用默认配置: {exc}")

        if override:
            for key in (
                "embedding_mode",
                "embedding_provider",
                "embedding_model",
                "embedding_api_key",
                "embedding_api_base_url",
            ):
                if override.get(key) is not None:
                    config[key] = override[key]

        mode = str(config.get("embedding_mode") or "local").strip().lower()
        if mode not in ("local", "api"):
            mode = "local"
        config["embedding_mode"] = mode

        provider = str(config.get("embedding_provider") or "openai").strip().lower()
        if provider not in ("openai", "custom"):
            provider = "openai"
        config["embedding_provider"] = provider

        if mode == "local":
            config["embedding_model"] = self.local_model_name
        else:
            model = str(config.get("embedding_model") or "").strip()
            config["embedding_model"] = model or self.default_api_model_name
            config["embedding_api_base_url"] = (
                str(config.get("embedding_api_base_url") or "").strip()
                or "https://api.openai.com/v1"
            )
            config["embedding_api_key"] = str(config.get("embedding_api_key") or "").strip()

        return config

    def _build_collection_name(self, user_id: str, project_id: str, embedding_config: Dict[str, Any]) -> str:
        """根据 embedding 配置生成 collection 名称。

        - local 模式保持历史命名，兼容旧数据。
        - api 模式按 provider+model 分集合，避免向量维度冲突。
        """
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
        project_hash = hashlib.sha256(project_id.encode()).hexdigest()[:8]
        base_name = f"u_{user_hash}_p_{project_hash}"

        if embedding_config.get("embedding_mode") != "api":
            return base_name

        namespace = f"{embedding_config.get('embedding_provider', 'openai')}:{embedding_config.get('embedding_model', '')}"
        embed_hash = hashlib.sha256(namespace.encode()).hexdigest()[:8]
        return f"{base_name}_e_{embed_hash}"

    def _list_project_collection_names(self, user_id: str, project_id: str) -> List[str]:
        """列出某个用户项目对应的所有 collection（含历史命名与多模型命名）。"""
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
        project_hash = hashlib.sha256(project_id.encode()).hexdigest()[:8]
        prefix = f"u_{user_hash}_p_{project_hash}"
        collection_names: List[str] = []

        try:
            for item in self.client.list_collections():
                name = item if isinstance(item, str) else getattr(item, "name", "")
                if name and name.startswith(prefix):
                    collection_names.append(name)
        except Exception as exc:
            logger.warning(f"⚠️ 获取collection列表失败: {exc}")

        return collection_names

    async def _embed_texts_with_api(self, texts: List[str], embedding_config: Dict[str, Any]) -> List[List[float]]:
        """通过 OpenAI 兼容 embeddings 接口生成向量。"""
        api_key = embedding_config.get("embedding_api_key", "")
        api_base_url = embedding_config.get("embedding_api_base_url", "")
        model = embedding_config.get("embedding_model", self.default_api_model_name)

        if not api_key:
            raise RuntimeError("Embedding API 模式已启用，但未配置 embedding_api_key")
        if not api_base_url:
            raise RuntimeError("Embedding API 模式已启用，但未配置 embedding_api_base_url")

        url = f"{api_base_url.rstrip('/')}/embeddings"
        payload = {"model": model, "input": texts}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        items = data.get("data", [])
        if not isinstance(items, list) or not items:
            raise RuntimeError("Embedding API 返回格式异常：缺少 data 字段")

        items = sorted(items, key=lambda x: x.get("index", 0))
        embeddings = [item.get("embedding") for item in items if item.get("embedding") is not None]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Embedding 数量不匹配: expected={len(texts)}, actual={len(embeddings)}"
            )
        return embeddings

    async def _embed_texts(
        self,
        texts: List[str],
        embedding_config: Dict[str, Any]
    ) -> List[List[float]]:
        """根据配置选择本地/API生成向量。"""
        if embedding_config.get("embedding_mode") == "api":
            return await self._embed_texts_with_api(texts, embedding_config)

        self._ensure_local_embedding_model()
        vectors = self.embedding_model.encode(texts).tolist()
        if vectors and isinstance(vectors[0], (int, float)):
            return [vectors]
        return vectors

    def get_collection(
        self,
        user_id: str,
        project_id: str,
        embedding_config: Optional[Dict[str, Any]] = None
    ):
        """
        获取或创建项目的记忆集合
        
        每个用户的每个项目有独立的 collection；API embedding 模式按 provider/model 分集合。
        """
        if embedding_config is None:
            embedding_config = {"embedding_mode": "local", "embedding_provider": "openai", "embedding_model": self.local_model_name}

        collection_name = self._build_collection_name(user_id, project_id, embedding_config)

        try:
            return self.client.get_or_create_collection(
                name=collection_name,
                metadata={
                    "user_id": user_id,
                    "project_id": project_id,
                    "embedding_mode": embedding_config.get("embedding_mode", "local"),
                    "embedding_provider": embedding_config.get("embedding_provider", "openai"),
                    "embedding_model": embedding_config.get("embedding_model", self.local_model_name),
                    "created_at": datetime.now().isoformat()
                }
            )
        except Exception as e:
            logger.error(f"❌ 获取collection失败: {str(e)}")
            raise
    
    async def add_memory(
        self,
        user_id: str,
        project_id: str,
        memory_id: str,
        content: str,
        memory_type: str,
        metadata: Dict[str, Any],
        db: Optional[AsyncSession] = None,
        embedding_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        添加记忆到向量数据库
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            memory_id: 记忆唯一ID
            content: 记忆内容(将被转换为向量)
            memory_type: 记忆类型
            metadata: 附加元数据
        
        Returns:
            是否添加成功
        """
        try:
            resolved_config = await self._resolve_embedding_config(
                user_id=user_id,
                db=db,
                override=embedding_config
            )
            collection = self.get_collection(user_id, project_id, resolved_config)

            # 生成文本的向量表示
            embedding = (await self._embed_texts([content], resolved_config))[0]
            
            # 准备元数据(ChromaDB要求所有值为基础类型)
            chroma_metadata = {
                "memory_type": memory_type,
                "chapter_id": str(metadata.get("chapter_id", "")),
                "chapter_number": int(metadata.get("chapter_number", 0)),
                "importance": float(metadata.get("importance_score", 0.5)),
                "tags": json.dumps(metadata.get("tags", []), ensure_ascii=False),
                "title": str(metadata.get("title", ""))[:200],  # 限制长度
                "is_foreshadow": int(metadata.get("is_foreshadow", 0)),
                "embedding_model": str(resolved_config.get("embedding_model", ""))[:200],
                "created_at": datetime.now().isoformat()
            }
            
            # 添加相关角色信息
            if metadata.get("related_characters"):
                chroma_metadata["related_characters"] = json.dumps(
                    metadata["related_characters"], 
                    ensure_ascii=False
                )
            
            # 存储到向量库
            collection.add(
                ids=[memory_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[chroma_metadata]
            )
            
            logger.info(f"✅ 记忆已添加: {memory_id[:8]}... (类型:{memory_type}, 重要性:{chroma_metadata['importance']})")
            return True
            
        except Exception as e:
            logger.error(f"❌ 添加记忆失败: {str(e)}")
            return False
    
    async def batch_add_memories(
        self,
        user_id: str,
        project_id: str,
        memories: List[Dict[str, Any]],
        db: Optional[AsyncSession] = None,
        embedding_config: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        批量添加记忆(性能更好)
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            memories: 记忆列表,每个包含id、content、type、metadata
        
        Returns:
            成功添加的数量
        """
        if not memories:
            return 0
            
        try:
            resolved_config = await self._resolve_embedding_config(
                user_id=user_id,
                db=db,
                override=embedding_config
            )
            collection = self.get_collection(user_id, project_id, resolved_config)
            
            ids = []
            documents = []
            metadatas = []
            documents_for_embedding = []
            
            # 批量准备数据
            for mem in memories:
                ids.append(mem['id'])
                documents.append(mem['content'])
                documents_for_embedding.append(mem['content'])
                
                # 准备元数据
                metadata = mem.get('metadata', {})
                chroma_metadata = {
                    "memory_type": mem['type'],
                    "chapter_id": str(metadata.get("chapter_id", "")),
                    "chapter_number": int(metadata.get("chapter_number", 0)),
                    "importance": float(metadata.get("importance_score", 0.5)),
                    "tags": json.dumps(metadata.get("tags", []), ensure_ascii=False),
                    "title": str(metadata.get("title", ""))[:200],
                    "is_foreshadow": int(metadata.get("is_foreshadow", 0)),
                    "embedding_model": str(resolved_config.get("embedding_model", ""))[:200],
                    "created_at": datetime.now().isoformat()
                }
                metadatas.append(chroma_metadata)

            # 批量生成embedding
            embeddings = await self._embed_texts(documents_for_embedding, resolved_config)
            
            # 批量添加
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
            logger.info(f"✅ 批量添加记忆成功: {len(memories)}条")
            return len(memories)
            
        except Exception as e:
            logger.error(f"❌ 批量添加记忆失败: {str(e)}")
            return 0
    
    async def search_memories(
        self,
        user_id: str,
        project_id: str,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10,
        min_importance: float = 0.0,
        chapter_range: Optional[tuple] = None,
        db: Optional[AsyncSession] = None,
        embedding_config: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        语义搜索相关记忆
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            query: 查询文本(会被转换为向量进行相似度搜索)
            memory_types: 过滤特定类型的记忆
            limit: 返回结果数量
            min_importance: 最低重要性阈值
            chapter_range: 章节范围 (start, end)
        
        Returns:
            相关记忆列表,按相似度排序
        """
        try:
            resolved_config = await self._resolve_embedding_config(
                user_id=user_id,
                db=db,
                override=embedding_config
            )
            collection = self.get_collection(user_id, project_id, resolved_config)
            
            # 生成查询向量
            query_embedding = (await self._embed_texts([query], resolved_config))[0]
            
            # 构建过滤条件 - ChromaDB要求使用$and组合多个条件
            where_filter = None
            conditions = []
            
            if memory_types:
                conditions.append({"memory_type": {"$in": memory_types}})
            if min_importance > 0:
                conditions.append({"importance": {"$gte": min_importance}})
            if chapter_range:
                conditions.append({"chapter_number": {"$gte": chapter_range[0]}})
                conditions.append({"chapter_number": {"$lte": chapter_range[1]}})
            
            # 根据条件数量选择合适的格式
            if len(conditions) == 0:
                where_filter = None
            elif len(conditions) == 1:
                where_filter = conditions[0]
            else:
                where_filter = {"$and": conditions}
            
            # 执行向量相似度搜索
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_filter
            )
            
            # 格式化结果
            memories = []
            if results['ids'] and results['ids'][0]:
                for i in range(len(results['ids'][0])):
                    memories.append({
                        "id": results['ids'][0][i],
                        "content": results['documents'][0][i],
                        "metadata": results['metadatas'][0][i],
                        "similarity": 1 - results['distances'][0][i] if 'distances' in results else 1.0,
                        "distance": results['distances'][0][i] if 'distances' in results else 0.0
                    })
            
            logger.info(f"🔍 语义搜索完成: 查询='{query[:30]}...', 找到{len(memories)}条记忆")
            return memories
            
        except Exception as e:
            logger.error(f"❌ 搜索记忆失败: {str(e)}")
            return []
    
    async def get_recent_memories(
        self,
        user_id: str,
        project_id: str,
        current_chapter: int,
        recent_count: int = 3,
        min_importance: float = 0.5,
        db: Optional[AsyncSession] = None
    ) -> List[Dict[str, Any]]:
        """
        获取最近几章的重要记忆(用于保持连贯性)
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            current_chapter: 当前章节号
            recent_count: 获取最近几章
            min_importance: 最低重要性阈值
        
        Returns:
            最近章节的记忆列表,按重要性排序
        """
        try:
            resolved_config = await self._resolve_embedding_config(user_id=user_id, db=db)
            collection = self.get_collection(user_id, project_id, resolved_config)
            
            # 计算章节范围
            start_chapter = max(1, current_chapter - recent_count)
            
            # 获取最近章节的记忆
            results = collection.get(
                where={
                    "$and": [
                        {"chapter_number": {"$gte": start_chapter}},
                        {"chapter_number": {"$lt": current_chapter}},
                        {"importance": {"$gte": min_importance}}
                    ]
                },
                limit=100  # 先获取足够多的记忆
            )
            
            memories = []
            if results['ids']:
                for i in range(len(results['ids'])):
                    memories.append({
                        "id": results['ids'][i],
                        "content": results['documents'][i],
                        "metadata": results['metadatas'][i]
                    })
            
            # 按重要性和章节号排序
            memories.sort(
                key=lambda x: (float(x['metadata'].get('importance', 0)), 
                              int(x['metadata'].get('chapter_number', 0))),
                reverse=True
            )
            
            # 返回最重要的前N条
            top_memories = memories[:20]
            logger.info(f"📚 获取最近记忆: 章节{start_chapter}-{current_chapter-1}, 找到{len(top_memories)}条")
            return top_memories
            
        except Exception as e:
            logger.error(f"❌ 获取最近记忆失败: {str(e)}")
            return []
    
    async def find_unresolved_foreshadows(
        self,
        user_id: str,
        project_id: str,
        current_chapter: int,
        db: Optional[AsyncSession] = None
    ) -> List[Dict[str, Any]]:
        """
        查找未完结的伏笔
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            current_chapter: 当前章节号
        
        Returns:
            未完结伏笔列表
        """
        try:
            resolved_config = await self._resolve_embedding_config(user_id=user_id, db=db)
            collection = self.get_collection(user_id, project_id, resolved_config)
            
            # 查找伏笔状态为1(已埋下但未回收)的记忆
            results = collection.get(
                where={
                    "$and": [
                        {"is_foreshadow": 1},
                        {"chapter_number": {"$lt": current_chapter}}
                    ]
                },
                limit=50
            )
            
            foreshadows = []
            if results['ids']:
                for i in range(len(results['ids'])):
                    foreshadows.append({
                        "id": results['ids'][i],
                        "content": results['documents'][i],
                        "metadata": results['metadatas'][i]
                    })
            
            # 按重要性排序
            foreshadows.sort(
                key=lambda x: float(x['metadata'].get('importance', 0)),
                reverse=True
            )
            
            logger.info(f"🎣 找到未完结伏笔: {len(foreshadows)}个")
            return foreshadows
            
        except Exception as e:
            logger.error(f"❌ 查找伏笔失败: {str(e)}")
            return []
    
    async def build_context_for_generation(
        self,
        user_id: str,
        project_id: str,
        current_chapter: int,
        chapter_outline: str,
        character_names: List[str] = None
    ) -> Dict[str, Any]:
        """
        为章节生成构建智能上下文
        
        这是核心功能: 结合多种检索策略,为AI生成提供最相关的记忆
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            current_chapter: 当前章节号
            chapter_outline: 本章大纲
            character_names: 涉及的角色名列表
        
        Returns:
            包含各种上下文信息的字典
        """
        logger.info(f"🧠 开始构建章节{current_chapter}的智能上下文...")
        
        # 1. 获取最近章节上下文(时间连续性)
        recent = await self.get_recent_memories(
            user_id, project_id, current_chapter, 
            recent_count=3, min_importance=0.5
        )
        
        # 2. 语义搜索相关记忆
        relevant = await self.search_memories(
            user_id=user_id,
            project_id=project_id,
            query=chapter_outline,
            limit=10,
            min_importance=0.4
        )
        
        # 3. 查找未完结伏笔
        foreshadows = await self.find_unresolved_foreshadows(
            user_id, project_id, current_chapter
        )
        
        # 4. 如果有指定角色,获取角色相关记忆
        character_memories = []
        if character_names:
            character_query = " ".join(character_names) + " 角色 状态 关系"
            character_memories = await self.search_memories(
                user_id=user_id,
                project_id=project_id,
                query=character_query,
                memory_types=["character_event", "plot_point"],
                limit=8
            )
        
        # 5. 获取重要情节点
        # 注意：ChromaDB的where条件需要特殊处理，不能同时使用多个顶层条件
        try:
            plot_points = await self.search_memories(
                user_id=user_id,
                project_id=project_id,
                query="重要 转折 高潮 关键",
                memory_types=["plot_point", "hook"],
                limit=5,
                min_importance=0.7
            )
        except Exception as e:
            logger.error(f"❌ 搜索记忆失败: {str(e)}")
            # 降级处理：分别查询
            plot_points = []
            try:
                plot_points = await self.search_memories(
                    user_id=user_id,
                    project_id=project_id,
                    query="重要 转折 高潮 关键",
                    memory_types=["plot_point", "hook"],
                    limit=5
                )
            except Exception as e2:
                logger.warning(f"⚠️ 降级查询也失败: {str(e2)}")
                plot_points = []
        
        context = {
            "recent_context": self._format_memories(recent, "最近章节记忆"),
            "relevant_memories": self._format_memories(relevant, "语义相关记忆"),
            "character_states": self._format_memories(character_memories, "角色相关记忆"),
            "foreshadows": self._format_memories(foreshadows[:5], "未完结伏笔"),
            "plot_points": self._format_memories(plot_points, "重要情节点"),
            "stats": {
                "recent_count": len(recent),
                "relevant_count": len(relevant),
                "character_count": len(character_memories),
                "foreshadow_count": len(foreshadows),
                "plot_point_count": len(plot_points)
            }
        }
        
        logger.info(f"✅ 上下文构建完成: 最近{len(recent)}条, 相关{len(relevant)}条, 伏笔{len(foreshadows)}个")
        return context
    def _format_memories(self, memories: List[Dict], section_title: str = "记忆") -> str:
        """
        格式化记忆列表为文本
        
        Args:
            memories: 记忆列表
            section_title: 章节标题
        
        Returns:
            格式化后的文本
        """
        if not memories:
            return f"【{section_title}】\n暂无相关记忆\n"
        
        lines = [f"【{section_title}】"]
        for i, mem in enumerate(memories, 1):
            meta = mem.get('metadata', {})
            chapter_num = meta.get('chapter_number', '?')
            mem_type = meta.get('memory_type', '未知')
            importance = float(meta.get('importance', 0.5))
            title = meta.get('title', '')
            content = mem['content']
            
            # 格式: [序号] 第X章-类型(重要性) 标题: 内容
            line = f"{i}. [第{chapter_num}章-{mem_type}★{importance:.1f}]"
            if title:
                line += f" {title}: {content[:100]}"
            else:
                line += f" {content[:150]}"
            lines.append(line)
        
        return "\n".join(lines) + "\n"
    
    async def delete_chapter_memories(
        self,
        user_id: str,
        project_id: str,
        chapter_id: str
    ) -> bool:
        """
        删除指定章节的所有记忆
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            chapter_id: 章节ID
        
        Returns:
            是否删除成功
        """
        try:
            collection_names = self._list_project_collection_names(user_id, project_id)
            if not collection_names:
                logger.info(f"ℹ️ 项目{project_id[:8]}未找到任何向量collection")
                return True

            deleted_count = 0
            for name in collection_names:
                collection = self.client.get_collection(name=name)
                results = collection.get(where={"chapter_id": chapter_id})
                if results.get('ids'):
                    collection.delete(ids=results['ids'])
                    deleted_count += len(results['ids'])

            if deleted_count > 0:
                logger.info(f"🗑️ 已删除章节{chapter_id[:8]}的{deleted_count}条记忆")
            else:
                logger.info(f"ℹ️ 章节{chapter_id[:8]}没有记忆需要删除")
            return True
                
        except Exception as e:
            logger.error(f"❌ 删除章节记忆失败: {str(e)}")
            return False
    
    async def delete_project_memories(
        self,
        user_id: str,
        project_id: str
    ) -> bool:
        """
        删除指定项目的所有记忆(包括向量数据库)
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
        
        Returns:
            是否删除成功
        """
        try:
            collection_names = self._list_project_collection_names(user_id, project_id)
            if not collection_names:
                logger.info(f"ℹ️ 项目{project_id[:8]}没有可删除的向量collection")
                return True

            for name in collection_names:
                self.client.delete_collection(name=name)
                logger.info(f"🗑️ 已删除项目{project_id[:8]}的向量数据库collection: {name}")
            return True
                
        except Exception as e:
            logger.error(f"❌ 删除项目记忆失败: {str(e)}")
            return False
    
    async def update_memory(
        self,
        user_id: str,
        project_id: str,
        memory_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
        embedding_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        更新记忆内容或元数据
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            memory_id: 记忆ID
            content: 新内容(可选)
            metadata: 新元数据(可选)
        
        Returns:
            是否更新成功
        """
        try:
            resolved_config = await self._resolve_embedding_config(
                user_id=user_id,
                db=db,
                override=embedding_config
            )
            collection = self.get_collection(user_id, project_id, resolved_config)
            
            update_data = {}
            
            if content:
                # 重新生成embedding
                embedding = (await self._embed_texts([content], resolved_config))[0]
                update_data['embeddings'] = [embedding]
                update_data['documents'] = [content]
            
            if metadata:
                # 准备新的元数据
                chroma_metadata = {}
                for key, value in metadata.items():
                    if isinstance(value, (list, dict)):
                        chroma_metadata[key] = json.dumps(value, ensure_ascii=False)
                    else:
                        chroma_metadata[key] = value
                update_data['metadatas'] = [chroma_metadata]
            
            if update_data:
                collection.update(
                    ids=[memory_id],
                    **update_data
                )
                logger.info(f"✅ 记忆已更新: {memory_id[:8]}...")
                return True
            else:
                logger.warning("⚠️ 没有提供更新内容")
                return False
                
        except Exception as e:
            logger.error(f"❌ 更新记忆失败: {str(e)}")
            return False
    
    async def get_memory_stats(
        self,
        user_id: str,
        project_id: str,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        获取记忆统计信息
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
        
        Returns:
            统计信息字典
        """
        try:
            resolved_config = await self._resolve_embedding_config(user_id=user_id, db=db)
            collection = self.get_collection(user_id, project_id, resolved_config)
            
            # 获取所有记忆
            all_memories = collection.get()
            
            if not all_memories['ids']:
                return {
                    "total_count": 0,
                    "by_type": {},
                    "by_chapter": {},
                    "foreshadow_count": 0
                }
            
            # 统计各类型数量
            type_counts = {}
            chapter_counts = {}
            foreshadow_count = 0
            
            for i, meta in enumerate(all_memories['metadatas']):
                mem_type = meta.get('memory_type', 'unknown')
                chapter_num = meta.get('chapter_number', 0)
                is_foreshadow = meta.get('is_foreshadow', 0)
                
                type_counts[mem_type] = type_counts.get(mem_type, 0) + 1
                chapter_counts[str(chapter_num)] = chapter_counts.get(str(chapter_num), 0) + 1
                
                if is_foreshadow == 1:
                    foreshadow_count += 1
            
            stats = {
                "total_count": len(all_memories['ids']),
                "by_type": type_counts,
                "by_chapter": chapter_counts,
                "foreshadow_count": foreshadow_count,
                "foreshadow_resolved": sum(1 for m in all_memories['metadatas'] if m.get('is_foreshadow') == 2)
            }
            
            logger.info(f"📊 记忆统计: 总计{stats['total_count']}条, 伏笔{foreshadow_count}个")
            return stats
            
        except Exception as e:
            logger.error(f"❌ 获取统计信息失败: {str(e)}")
            return {"error": str(e)}


# 创建全局实例
memory_service = MemoryService()
            
