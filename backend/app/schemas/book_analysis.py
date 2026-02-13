"""拆书分析相关请求/响应模型"""
from pydantic import BaseModel, Field


class ChapterPreview(BaseModel):
    """章节预览信息"""

    index: int = Field(..., description="章节索引（从1开始）")
    chapter_number: int = Field(..., description="识别出的章节号")
    title: str = Field(..., description="章节标题")
    word_count: int = Field(..., description="章节字数")
    preview: str = Field(..., description="章节内容预览")


class BookSplitRequest(BaseModel):
    """章节拆分请求"""

    content: str = Field(..., min_length=20, max_length=2_000_000, description="原始小说文本")
    min_chapter_length: int = Field(100, ge=20, le=5000, description="最小章节长度")
    fallback_paragraph_group_size: int = Field(50, ge=5, le=200, description="回退分组段落数")


class BookSplitResponse(BaseModel):
    """章节拆分响应"""

    total_chapters: int = Field(..., description="识别到的章节总数")
    detected_by_heading: bool = Field(..., description="是否通过章节标题识别")
    chapters: list[ChapterPreview] = Field(..., description="章节预览列表")
    note: str | None = Field(None, description="附加说明")


class BookAnalyzeRequest(BaseModel):
    """拆书分析请求"""

    content: str = Field(..., min_length=20, max_length=2_000_000, description="原始小说文本")
    project_id: str | None = Field(None, description="目标项目ID（用于写入Embedding）")
    enable_embedding: bool = Field(False, description="是否将拆书内容写入向量库")
    embedding_chunk_size: int = Field(1800, ge=300, le=4000, description="向量切片长度")
    start_chapter: int | None = Field(None, ge=1, le=100000, description="起始章节索引（含）")
    end_chapter: int | None = Field(None, ge=1, le=100000, description="结束章节索引（含）")
    min_chapter_length: int = Field(100, ge=20, le=5000, description="最小章节长度")
    fallback_paragraph_group_size: int = Field(50, ge=5, le=200, description="回退分组段落数")
    max_chars: int = Field(160000, ge=5000, le=400000, description="送入模型的最大字符数")

class BookAnalyzeResponse(BaseModel):
    """拆书分析响应"""

    total_chapters: int = Field(..., description="识别到的章节总数")
    analyzed_range: str = Field(..., description="本次分析的章节范围")
    analyzed_chars: int = Field(..., description="实际送入模型的字符数")
    truncated: bool = Field(..., description="是否触发长度截断")
    result_markdown: str = Field(..., description="AI返回的Markdown表格")
    chapters: list[ChapterPreview] = Field(..., description="本次分析使用的章节列表")
    embedding_enabled: bool = Field(False, description="是否启用了向量写入")
    embedding_project_id: str | None = Field(None, description="写入向量库的项目ID")
    embedding_saved_count: int = Field(0, description="成功写入向量条数")
    embedding_error: str | None = Field(None, description="向量写入失败信息")
