"""拆书分析 API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access
from app.api.settings import get_user_ai_service
from app.database import get_db
from app.logger import get_logger
from app.schemas.book_analysis import (
    BookSplitRequest,
    BookSplitResponse,
    BookAnalyzeRequest,
    BookAnalyzeResponse,
    ChapterPreview,
)
from app.services.ai_service import AIService
from app.services.book_analysis_service import (
    split_book_content,
    select_chapter_range,
    build_analysis_source_text,
    build_book_analysis_prompt,
    build_embedding_memory_records,
)
from app.services.memory_service import memory_service

router = APIRouter(prefix="/book-analysis", tags=["拆书分析"])
logger = get_logger(__name__)


def _to_preview(chapter) -> ChapterPreview:
    return ChapterPreview(
        index=chapter.index,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        word_count=chapter.word_count,
        preview=chapter.preview,
    )


@router.post("/split", response_model=BookSplitResponse, summary="拆分章节")
async def split_book(data: BookSplitRequest) -> BookSplitResponse:
    """将原始小说文本拆分为章节并返回预览"""
    chapters, detected_by_heading = split_book_content(
        content=data.content,
        min_chapter_length=data.min_chapter_length,
        fallback_paragraph_group_size=data.fallback_paragraph_group_size,
    )

    if not chapters:
        raise HTTPException(status_code=400, detail="未识别到可分析的章节，请检查文本格式或内容长度")

    note = None
    if not detected_by_heading:
        note = "未检测到稳定的章节标题，已按段落分组生成分析片段"

    return BookSplitResponse(
        total_chapters=len(chapters),
        detected_by_heading=detected_by_heading,
        chapters=[_to_preview(ch) for ch in chapters],
        note=note,
    )


@router.post("/analyze", response_model=BookAnalyzeResponse, summary="执行拆书分析")
async def analyze_book(
    data: BookAnalyzeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ai_service: AIService = Depends(get_user_ai_service),
) -> BookAnalyzeResponse:
    """
    执行拆书分析：
    1. 自动识别章节
    2. 选择章节范围
    3. 生成结构化拆书表格（Markdown）
    """
    chapters, _ = split_book_content(
        content=data.content,
        min_chapter_length=data.min_chapter_length,
        fallback_paragraph_group_size=data.fallback_paragraph_group_size,
    )

    if data.start_chapter and data.end_chapter and data.start_chapter > data.end_chapter:
        raise HTTPException(status_code=400, detail="start_chapter 不能大于 end_chapter")

    if data.enable_embedding and not data.project_id:
        raise HTTPException(status_code=400, detail="启用 embedding 时必须提供 project_id")

    if not chapters:
        raise HTTPException(status_code=400, detail="未识别到可分析的章节，请检查文本格式或内容长度")

    selected_chapters, start, end = select_chapter_range(
        chapters=chapters,
        start_chapter=data.start_chapter,
        end_chapter=data.end_chapter,
    )

    if not selected_chapters:
        raise HTTPException(
            status_code=400,
            detail=f"章节范围无效：start={data.start_chapter}, end={data.end_chapter}, 可选范围为 1-{len(chapters)}",
        )

    source_text = build_analysis_source_text(selected_chapters)
    truncated = len(source_text) > data.max_chars
    final_source_text = source_text[:data.max_chars] if truncated else source_text

    prompt = build_book_analysis_prompt(final_source_text)
    logger.info(
        "开始拆书分析：chapters=%s, range=%s-%s, chars=%s, truncated=%s",
        len(chapters),
        start,
        end,
        len(final_source_text),
        truncated,
    )

    result_chunks: list[str] = []
    try:
        async for chunk in ai_service.generate_text_stream(
            prompt=prompt,
            temperature=0.3,
            auto_mcp=False,
        ):
            result_chunks.append(chunk)
    except Exception as exc:
        logger.error("拆书分析调用AI失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"拆书分析失败: {str(exc)}")

    result_markdown = "".join(result_chunks).strip()
    if not result_markdown:
        raise HTTPException(status_code=502, detail="AI未返回有效分析结果，请重试")

    embedding_enabled = False
    embedding_project_id = None
    embedding_saved_count = 0
    embedding_error = None

    if data.enable_embedding:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="未登录")

        # 防御性检查
        if not data.project_id:
            raise HTTPException(status_code=400, detail="启用 embedding 时必须提供 project_id")

        await verify_project_access(data.project_id, user_id, db)

        embedding_enabled = True
        embedding_project_id = data.project_id

        try:
            embedding_records = build_embedding_memory_records(
                chapters=selected_chapters,
                result_markdown=result_markdown,
                analyzed_range=f"{start}-{end}",
                chunk_size=data.embedding_chunk_size,
            )
            embedding_saved_count = await memory_service.batch_add_memories(
                user_id=user_id,
                project_id=data.project_id,
                memories=embedding_records,
                db=db,
            )
            logger.info(
                "拆书分析向量写入完成: project=%s, saved=%s/%s",
                data.project_id[:8],
                embedding_saved_count,
                len(embedding_records),
            )
        except Exception as exc:
            embedding_error = str(exc)
            logger.error("拆书分析向量写入失败: %s", exc, exc_info=True)

    return BookAnalyzeResponse(
        total_chapters=len(chapters),
        analyzed_range=f"{start}-{end}",
        analyzed_chars=len(final_source_text),
        truncated=truncated,
        result_markdown=result_markdown,
        chapters=[_to_preview(ch) for ch in selected_chapters],
        embedding_enabled=embedding_enabled,
        embedding_project_id=embedding_project_id,
        embedding_saved_count=embedding_saved_count,
        embedding_error=embedding_error,
    )
