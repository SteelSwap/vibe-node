"""Document-structure-aware chunking for spec documents.

Chunks markdown by heading structure with hierarchical title tracking.
Each chunk carries document_title, section_title, subsection_title,
and an embed_text that includes the full hierarchy
for better embedding quality.
"""

import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class SpecChunk:
    """A chunk of a spec document ready for DB insertion."""
    document_title: str
    section_title: str | None
    subsection_title: str | None
    content_markdown: str
    content_plain: str
    embed_text: str
    chunk_type: str  # section, definition, rule, schema, agda
    content_hash: str
    metadata: dict = field(default_factory=dict)


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting for plain text BM25 indexing."""
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\(.*?\)', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[*_]{1,3}([^*_]+)[*_]{1,3}', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _build_embed_text(
    document_title: str,
    section_title: str | None,
    subsection_title: str | None,
    content_plain: str,
    source_repo: str | None = None,
    source_path: str | None = None,
) -> str:
    """Build the text that gets embedded — includes hierarchical context."""
    parts = []
    if source_repo:
        parts.append(f"Source: {source_repo}")
    if source_path:
        parts.append(f"File: {source_path}")
    parts.append(f"Document: {document_title}")
    if section_title:
        parts.append(f"Section: {section_title}")
    if subsection_title:
        parts.append(f"Subsection: {subsection_title}")
    parts.append("")
    parts.append(content_plain)
    return "\n".join(parts)


def chunk_markdown(
    content: str,
    source_path: str,
    source_repo: str = "",
) -> list[SpecChunk]:
    """Chunk markdown by heading structure with hierarchical titles.

    Tracks h1 → document_title, h2 → section_title, h3 → subsection_title.
    """
    # Derive document title from filename
    doc_title = source_path.split("/")[-1].replace(".md", "").replace("-", " ").title()

    current_section: str | None = None
    current_subsection: str | None = None
    current_content: list[str] = []
    sections: list[tuple[str | None, str | None, str]] = []

    for line in content.split("\n"):
        h1_match = re.match(r'^#\s+(.+)$', line)
        h2_match = re.match(r'^##\s+(.+)$', line)
        h3_match = re.match(r'^###\s+(.+)$', line)

        if h1_match:
            # Save previous section
            if current_content:
                text = "\n".join(current_content).strip()
                if text:
                    sections.append((current_section, current_subsection, text))
            doc_title = h1_match.group(1).strip()
            current_section = None
            current_subsection = None
            current_content = [line]
        elif h2_match:
            if current_content:
                text = "\n".join(current_content).strip()
                if text:
                    sections.append((current_section, current_subsection, text))
            current_section = h2_match.group(1).strip()
            current_subsection = None
            current_content = [line]
        elif h3_match:
            if current_content:
                text = "\n".join(current_content).strip()
                if text:
                    sections.append((current_section, current_subsection, text))
            current_subsection = h3_match.group(1).strip()
            current_content = [line]
        else:
            current_content.append(line)

    # Save last section
    if current_content:
        text = "\n".join(current_content).strip()
        if text:
            sections.append((current_section, current_subsection, text))

    # Convert to chunks
    chunks: list[SpecChunk] = []
    for idx, (sec, subsec, md_content) in enumerate(sections):
        plain = _strip_markdown(md_content)
        if len(plain) < 50 and chunks:
            # Merge tiny sections with previous
            prev = chunks[-1]
            merged_md = prev.content_markdown + "\n\n" + md_content
            merged_plain = prev.content_plain + "\n\n" + plain
            merged_embed = _build_embed_text(
                doc_title, prev.section_title, prev.subsection_title,
                merged_plain, source_repo, source_path,
            )
            chunks[-1] = SpecChunk(
                document_title=doc_title,
                section_title=prev.section_title,
                subsection_title=prev.subsection_title,
                content_markdown=merged_md,
                content_plain=merged_plain,
                embed_text=merged_embed,
                chunk_type=prev.chunk_type,
                content_hash=_content_hash(merged_md),
            )
        else:
            embed = _build_embed_text(
                doc_title, sec, subsec, plain, source_repo, source_path,
            )
            chunks.append(SpecChunk(
                document_title=doc_title,
                section_title=sec,
                subsection_title=subsec,
                content_markdown=md_content,
                content_plain=plain,
                embed_text=embed,
                chunk_type="section",
                content_hash=_content_hash(md_content),
            ))

    return chunks


def chunk_cddl(
    content: str,
    source_path: str,
    source_repo: str = "",
) -> list[SpecChunk]:
    """Chunk CDDL by top-level rule definitions."""
    doc_title = source_path.split("/")[-1]
    chunks: list[SpecChunk] = []
    current_lines: list[str] = []
    current_name = doc_title

    for line in content.split("\n"):
        if line and not line[0].isspace() and "=" in line and current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                md = f"```cddl\n{text}\n```"
                embed = _build_embed_text(
                    doc_title, current_name, None, text, source_repo, source_path,
                )
                chunks.append(SpecChunk(
                    document_title=doc_title,
                    section_title=current_name,
                    subsection_title=None,
                    content_markdown=md,
                    content_plain=text,
                    embed_text=embed,
                    chunk_type="schema",
                    content_hash=_content_hash(md),
                ))
            current_name = line.split("=")[0].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            md = f"```cddl\n{text}\n```"
            embed = _build_embed_text(
                doc_title, current_name, None, text, source_repo, source_path,
            )
            chunks.append(SpecChunk(
                document_title=doc_title,
                section_title=current_name,
                subsection_title=None,
                content_markdown=md,
                content_plain=text,
                embed_text=embed,
                chunk_type="schema",
                content_hash=_content_hash(md),
            ))

    return chunks
