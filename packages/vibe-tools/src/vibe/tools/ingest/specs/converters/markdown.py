"""Markdown converter — direct passthrough with frontmatter stripping."""


def convert_markdown(content: str) -> str:
    """Convert markdown content. Strips YAML frontmatter if present."""
    # Strip YAML frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3 :].strip()
    return content
