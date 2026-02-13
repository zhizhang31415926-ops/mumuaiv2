"""拆书分析服务：章节识别、范围选择与提示词构建"""
from __future__ import annotations

from dataclasses import dataclass
import re
import uuid
from typing import Any, Dict, List, Tuple


CHAPTER_HEADING_PATTERN = re.compile(
    r"(^\s*(?:第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章回节卷篇]|(?:Chapter|CHAPTER)\s*\d+|序章|楔子|尾声|后记|番外)[^\n]*$)",
    re.MULTILINE,
)

CN_NUMBER_PATTERN = re.compile(r"[零〇一二三四五六七八九十百千万两]+")
DIGIT_PATTERN = re.compile(r"\d+")

CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

CN_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
}


@dataclass
class SplitChapter:
    """拆分后的章节结构"""

    index: int
    chapter_number: int
    title: str
    content: str
    word_count: int
    preview: str


def normalize_text(content: str) -> str:
    """统一换行并清理首尾空白"""
    return content.replace("\r\n", "\n").replace("\r", "\n").strip()


def chinese_to_int(text: str) -> int | None:
    """中文数字转阿拉伯数字，支持到万位"""
    raw = text.strip()
    if not raw:
        return None

    if raw.isdigit():
        return int(raw)

    total = 0
    section = 0
    number = 0

    for ch in raw:
        if ch in CN_DIGITS:
            number = CN_DIGITS[ch]
            continue

        unit = CN_UNITS.get(ch)
        if unit is None:
            return None

        if unit == 10000:
            section = (section + number) * unit
            total += section
            section = 0
            number = 0
            continue

        if number == 0:
            number = 1
        section += number * unit
        number = 0

    value = total + section + number
    return value if value > 0 else None


def extract_chapter_number(title: str, fallback_index: int) -> int:
    """从标题中提取章节号，无法识别时回退为顺序号"""
    digit_match = DIGIT_PATTERN.search(title)
    if digit_match:
        return int(digit_match.group(0))

    cn_match = CN_NUMBER_PATTERN.search(title)
    if cn_match:
        converted = chinese_to_int(cn_match.group(0))
        if converted:
            return converted

    return fallback_index


def _build_preview(content: str, limit: int = 140) -> str:
    one_line = " ".join(content.split())
    if len(one_line) <= limit:
        return one_line
    return f"{one_line[:limit]}..."


def split_book_content(
    content: str,
    min_chapter_length: int = 100,
    fallback_paragraph_group_size: int = 50,
) -> Tuple[List[SplitChapter], bool]:
    """
    拆分文本为章节

    Returns:
        (chapters, detected_by_heading)
    """
    text = normalize_text(content)
    if not text:
        return [], False

    parts = re.split(CHAPTER_HEADING_PATTERN, text)
    chapters: List[SplitChapter] = []
    detected_by_heading = False

    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            title = (parts[i] or "").strip()
            chapter_content = (parts[i + 1] if i + 1 < len(parts) else "").strip()
            if not title or len(chapter_content) < min_chapter_length:
                continue

            index = len(chapters) + 1
            chapters.append(
                SplitChapter(
                    index=index,
                    chapter_number=extract_chapter_number(title, index),
                    title=title,
                    content=chapter_content,
                    word_count=len(chapter_content),
                    preview=_build_preview(chapter_content),
                )
            )

        detected_by_heading = len(chapters) > 0

    if chapters:
        return chapters, detected_by_heading

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return [], False

    fallback_chapters: List[SplitChapter] = []
    for i in range(0, len(paragraphs), fallback_paragraph_group_size):
        group = paragraphs[i:i + fallback_paragraph_group_size]
        grouped_text = "\n\n".join(group).strip()
        if len(grouped_text) < min_chapter_length:
            continue

        index = len(fallback_chapters) + 1
        title = f"段落组{index}"
        fallback_chapters.append(
            SplitChapter(
                index=index,
                chapter_number=index,
                title=title,
                content=grouped_text,
                word_count=len(grouped_text),
                preview=_build_preview(grouped_text),
            )
        )

    return fallback_chapters, False


def select_chapter_range(
    chapters: List[SplitChapter],
    start_chapter: int | None,
    end_chapter: int | None,
) -> Tuple[List[SplitChapter], int, int]:
    """根据起止章节选择分析范围（基于章节索引，从1开始）"""
    if not chapters:
        return [], 0, 0

    max_index = len(chapters)
    start = start_chapter or 1
    end = end_chapter or max_index

    if start > max_index:
        return [], start, end

    start = max(1, start)
    end = min(max_index, end)
    if start > end:
        return [], start, end

    selected = [ch for ch in chapters if start <= ch.index <= end]
    return selected, start, end


def build_analysis_source_text(chapters: List[SplitChapter]) -> str:
    """将选中的章节拼接为分析输入文本"""
    lines: List[str] = []
    for chapter in chapters:
        lines.append(f"{chapter.title}\n{chapter.content}")
    return "\n\n".join(lines).strip()


def build_book_analysis_prompt(content: str) -> str:
    """构建拆书分析提示词（参考 SmartReads 的输出规范）"""
    return f"""# 角色
你是一位经验丰富的小说编辑和剧情分析师，擅长拆解章节结构并给出可复用的创作洞察。

# 任务
阅读我提供的小说正文，逐章输出一份单一的 Markdown 表格，用于“拆书分析”。

# 表格结构（必须严格 8 列）
| 章节号 | 章节标题 | 章节核心剧情梗概 | 本章核心功能/目的 | 画面感/镜头序列 | 关键情节点 (Key Points) | 本章氛围/情绪 | 结尾\"钩子\" (Hook) |

各列要求：
1. 章节号：从标题提取，统一为阿拉伯数字。
2. 章节标题：保留原始标题信息。
3. 章节核心剧情梗概：2-3句，回答“谁做了什么，导致了什么”。
4. 本章核心功能/目的：解释本章在全书结构中的作用。
5. 画面感/镜头序列：必须是 JSON 数组字符串，3-5 个镜头。
6. 关键情节点：必须是 JSON 数组字符串，列出驱动剧情前进的关键节点。
7. 本章氛围/情绪：必须是 JSON 数组字符串。
8. 结尾“钩子”：概括章节结尾的悬念或期待点。

# 输出硬性约束
1. 只允许输出 Markdown 表格，不要输出任何解释性文字。
2. 输出必须以 `| 章节号 |` 开头。
3. 每一章对应一行，保持列顺序不变。
4. 当信息不足时，基于文本做谨慎推断，避免编造不存在的剧情。

以下是正文：

{content}
"""


def split_text_for_embedding(
    text: str,
    chunk_size: int = 1800,
    overlap: int = 150,
) -> List[str]:
    """将长文本切分为适合 embedding 的小片段"""
    cleaned = " ".join(text.split())
    if not cleaned:
        return []

    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: List[str] = []
    step = max(1, chunk_size - overlap)
    start = 0

    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        part = cleaned[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(cleaned):
            break
        start += step

    return chunks


def build_embedding_memory_records(
    chapters: List[SplitChapter],
    result_markdown: str,
    analyzed_range: str,
    chunk_size: int = 1800,
) -> List[Dict[str, Any]]:
    """构建用于向量存储的记忆记录"""
    records: List[Dict[str, Any]] = []

    for chapter in chapters:
        full_text = f"{chapter.title}\n{chapter.content}"
        parts = split_text_for_embedding(full_text, chunk_size=chunk_size)
        total_parts = max(1, len(parts))

        for idx, part in enumerate(parts, start=1):
            records.append(
                {
                    "id": str(uuid.uuid4()),
                    "content": part,
                    "type": "book_analysis_chapter",
                    "metadata": {
                        "chapter_id": f"book_analysis_{chapter.index}",
                        "chapter_number": chapter.chapter_number,
                        "importance_score": 0.65,
                        "tags": [
                            "book_analysis",
                            "chapter_segment",
                            f"chapter_{chapter.chapter_number}",
                        ],
                        "title": f"{chapter.title}（片段{idx}/{total_parts}）",
                        "is_foreshadow": 0,
                    },
                }
            )

    result_parts = split_text_for_embedding(result_markdown, chunk_size=chunk_size)
    total_result_parts = max(1, len(result_parts))
    for idx, part in enumerate(result_parts, start=1):
        records.append(
            {
                "id": str(uuid.uuid4()),
                "content": part,
                "type": "book_analysis_result",
                "metadata": {
                    "chapter_id": "book_analysis_result",
                    "chapter_number": 0,
                    "importance_score": 0.8,
                    "tags": [
                        "book_analysis",
                        "analysis_result",
                        f"range_{analyzed_range}",
                    ],
                    "title": f"拆书分析结果（片段{idx}/{total_result_parts}）",
                    "is_foreshadow": 0,
                },
            }
        )

    return records
