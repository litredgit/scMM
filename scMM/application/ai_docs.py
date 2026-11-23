"""Select bounded excerpts from the guides distributed with this scMM version."""

import re
import sysconfig
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GUIDES = {
    "projects-and-data.md": "项目与数据",
    "extraction.md": "细胞提取",
    "annotation.md": "特征注释",
    "statistics.md": "统计分析",
}
PAGE_GUIDES = {
    "account": ("projects-and-data.md", "AI 分析助手"),
    "results": ("projects-and-data.md", "图表、作图数据和报告"),
    "samples": ("extraction.md", "添加文件与选择样本"),
    "cell-extraction": ("extraction.md", "添加文件与选择样本"),
    "raw": ("extraction.md", "预览与应用参数"),
    "extraction": ("extraction.md", "提取、停止与审核"),
    "annotation": ("annotation.md", "候选与关系审核"),
    "annotation-evidence": ("annotation.md", "证据与导入"),
    "ions": ("annotation.md", "离子归组与化合物证据"),
    "statistics": ("statistics.md", "选择分析与核对结果"),
    "data-check": ("statistics.md", "数据检查与数据编辑"),
    "data-editor": ("statistics.md", "数据检查与数据编辑"),
    "preprocess": ("statistics.md", "预处理与 QC"),
    "analysis": ("statistics.md", "选择分析与核对结果"),
    "parameters": ("projects-and-data.md", "网页帮助与按钮"),
}
MAX_EXCERPTS = 3
MAX_EXCERPT_CHARS = 1200

_DOC_REQUEST = re.compile(r"使用指南|文档|指南|手册|\b(?:docs?|documentation|manual|guide)\b")
_HOW_TO = re.compile(
    r"如何使用|怎么操作|怎么用|如何|怎么|怎样|哪里|在哪|什么意思|是什么|含义|默认|区别|"
    r"\b(?:how to|how do|how can|what does|meaning|default|difference)\b"
)
_PAGE_REQUEST = re.compile(
    r"当前页面|这个页面|这一页|这页|本页|这一步|当前步骤|本步骤|this page|this step"
)
_QUESTION_WORDS = re.compile(
    r"请问|请|帮我|我要|我想|查一下|查阅|查找|查看|参考|告诉我|项目|当前|这个|有关|相关|"
    r"网页|参数|的值|方法|能否|一下|用什么|多少|\b(?:a|an|is|the|i|for|in|of|to|on|and|scmm)\b"
)
_WORD = re.compile(r"[a-z][a-z0-9_]+|[\u3400-\u9fff]+")
_HEADING = re.compile(r"^#{2,6}[ \t]+(.+)$", re.MULTILINE)
_FENCE = re.compile(r"^```[^\n]*\n.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^\n)]*\)")
_IMPUTE_TERMS = frozenset({"插补", "填补", "impute"})
_METHOD_NAMES = frozenset(
    {
        "umap",
        "pca",
        "kmeans",
        "leiden",
        "louvain",
        "dbscan",
        "knn",
        "pqn",
        "shap",
        "palantir",
        "snr_v1",
    }
)


@dataclass(frozen=True)
class GuideSection:
    file: str
    heading: str
    body: str
    heading_terms: frozenset[str]
    body_terms: frozenset[str]


def _terms(text):
    words = set()
    for word in _WORD.findall(unicodedata.normalize("NFKC", text).casefold()):
        if word.isascii():
            words.add(word)
        else:
            words.update(word[i : i + 2] for i in range(len(word) - 1))
    return frozenset(words)


def _guide_root():
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").is_file():
        return checkout / "docs"
    return Path(sysconfig.get_path("data")) / "share" / "scmm" / "guides"


@lru_cache(maxsize=1)
def _sections(root):
    sections = []
    if root.is_symlink():
        return sections
    for name in GUIDES:
        file = root / name
        try:
            if file.resolve(strict=True) != root / name or not file.is_file():
                continue
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError, RuntimeError):
            continue
        parts = _HEADING.split(_FENCE.sub("", text))
        for title, content in zip(parts[1::2], parts[2::2], strict=True):
            title, content = title.strip(), _LINK.sub(r"\1", content).strip()
            if content and title != "建议的项目数据目录":
                sections.append(GuideSection(name, title, content, _terms(title), _terms(content)))
    return sections


def _excerpt(section, terms, priority):
    body = section.body
    if len(body) <= MAX_EXCERPT_CHARS:
        return body

    def relevance(text):
        found = _terms(text) & terms
        return len(found & priority), len(found)

    paragraph = max(body.split("\n\n"), key=relevance)
    if len(paragraph) > MAX_EXCERPT_CHARS:
        lines = paragraph.splitlines()
        best = max(range(len(lines)), key=lambda i: relevance(lines[i]))
        paragraph = "\n".join(lines[max(0, best - 1) :])
    if len(paragraph) > MAX_EXCERPT_CHARS:
        return paragraph[: MAX_EXCERPT_CHARS - 1].rstrip() + "…"
    return paragraph


def lookup_guides(question, page):
    query = unicodedata.normalize("NFKC", question).casefold()
    explicit = _DOC_REQUEST.search(query)
    if not explicit and not _HOW_TO.search(query):
        return None
    page_request = _PAGE_REQUEST.search(query)
    subject = _HOW_TO.sub(" ", _PAGE_REQUEST.sub(" ", _DOC_REQUEST.sub(" ", query)))
    terms = _terms(_QUESTION_WORDS.sub(" ", subject))
    if terms & _IMPUTE_TERMS:
        terms |= _IMPUTE_TERMS
    methods = terms & _METHOD_NAMES
    priority = {t for t in terms if t.isascii()}
    guide, default_heading = PAGE_GUIDES.get(page, ("projects-and-data.md", "选择交换格式"))
    sections = _sections(_guide_root())

    ranked = []
    for section in sections:
        matches = section.body_terms & terms
        heading_matches = section.heading_terms & terms
        if methods and not (matches | heading_matches) & methods:
            continue
        if not heading_matches and len(matches) < 2 and not any(t.isascii() for t in matches):
            continue
        score = 4 * len(matches | heading_matches) + 2 * len(heading_matches)
        score += 8 * len((matches | heading_matches) & priority)
        score += 5 * (section.file == guide)
        score += 4 * (section.file == guide and section.heading == default_heading)
        if "默认" in query or "参数" in query:
            score += 3 * ("参数" in section.heading)
        ranked.append((score, section))

    if ranked:
        ranked.sort(key=lambda item: item[0], reverse=True)
        cutoff = max(4, ranked[0][0] * 0.6)
        selected = [section for score, section in ranked[:MAX_EXCERPTS] if score >= cutoff]
    elif not terms or page_request:
        selected = [
            section
            for section in sections
            if section.file == guide and section.heading == default_heading
        ][:1]
    else:
        return []
    return [
        {
            "guide": GUIDES[section.file],
            "section": section.heading,
            "excerpt": _excerpt(section, terms, priority),
        }
        for section in selected
    ]
