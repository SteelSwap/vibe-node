"""Literate Agda converter — extracts prose and code blocks."""

import re


def convert_agda(content: str) -> str:
    """Convert literate Agda (.lagda) to markdown.

    Literate Agda format:
    - Text between \\begin{code} / \\end{code} is Agda code
    - Everything else is LaTeX prose
    - \\begin{code}[hide] blocks are infrastructure (skip them)
    """
    lines = content.split("\n")
    output: list[str] = []
    in_code = False
    hidden = False

    for line in lines:
        if re.match(r"\\begin\{code\}\[hide\]", line):
            in_code = True
            hidden = True
            continue
        elif re.match(r"\\begin\{code\}", line):
            in_code = True
            hidden = False
            output.append("```agda")
            continue
        elif re.match(r"\\end\{code\}", line):
            if not hidden:
                output.append("```")
            in_code = False
            hidden = False
            continue

        if in_code and hidden:
            continue
        elif in_code:
            output.append(line)
        else:
            # LaTeX prose — basic cleanup
            # Convert \section{} to markdown headings
            line = re.sub(r"\\section\{(.+?)\}", r"# \1", line)
            line = re.sub(r"\\subsection\{(.+?)\}", r"## \1", line)
            line = re.sub(r"\\subsubsection\{(.+?)\}", r"### \1", line)
            # Convert \emph and \textbf
            line = re.sub(r"\\emph\{(.+?)\}", r"*\1*", line)
            line = re.sub(r"\\textbf\{(.+?)\}", r"**\1**", line)
            # Strip other LaTeX commands but keep content
            line = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", line)
            output.append(line)

    return "\n".join(output)
