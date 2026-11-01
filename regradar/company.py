"""The synthetic company's policy documents (company/*.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

COMPANY_DIR = Path(__file__).resolve().parent.parent / "company"
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
REQUIRED_FIELDS = ("doc_id", "title", "entity", "synthetic", "owner", "version", "effective")


@dataclass(frozen=True)
class PolicyDocument:
    doc_id: str
    title: str
    path: Path
    fields: dict[str, str]
    body: str

    @property
    def synthetic(self) -> bool:
        return self.fields.get("synthetic") == "true"


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """`key: value` lines between the opening `---` fences, and the rest."""
    match = _FRONT_MATTER.match(text)
    if not match:
        raise ValueError("no front matter")
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields, text[match.end() :]


def load_policies(folder: Path = COMPANY_DIR) -> list[PolicyDocument]:
    """Every policy document, in file order. The README and the gap key are not policies."""
    documents = []
    for path in sorted(folder.glob("[0-9][0-9]_*.md")):
        fields, body = parse_front_matter(path.read_text(encoding="utf-8"))
        missing = [name for name in REQUIRED_FIELDS if name not in fields]
        if missing:
            raise ValueError(f"{path.name}: missing {', '.join(missing)}")
        documents.append(PolicyDocument(fields["doc_id"], fields["title"], path, fields, body))
    return documents


@dataclass(frozen=True)
class PolicySection:
    """One numbered paragraph of a policy, the unit a finding cites ("FC-13 §4.1")."""

    doc_id: str
    section: str  # "4.1"; a heading's number ("5") for text under a heading with no paragraphs
    heading: str
    text: str
    title: str
    owner: str
    entity: str

    @property
    def ref(self) -> str:
        return f"{self.doc_id} §{self.section}"


_HEADING = re.compile(r"^## (\d+)\.\s*(.+)$")
_PARAGRAPH = re.compile(r"^(\d+\.\d+[a-z]?)\s+(.*)$")


def policy_sections(documents: list[PolicyDocument] | None = None) -> list[PolicySection]:
    """Every numbered paragraph of every policy, with the policy's owner and entity."""
    out: list[PolicySection] = []
    for doc in documents if documents is not None else load_policies():
        # (section number, heading, lines); text under a heading before any
        # numbered paragraph is filed under the heading's own number.
        blocks: list[tuple[str, str, list[str]]] = []
        heading_no = heading = ""
        for line in doc.body.splitlines():
            if line.startswith(">") or line.startswith("# "):
                continue
            if m := _HEADING.match(line):
                heading_no, heading = m.group(1), m.group(2).strip()
                blocks.append((heading_no, heading, []))
            elif (
                heading_no
                and (m := _PARAGRAPH.match(line))
                and m.group(1).startswith(f"{heading_no}.")
            ):
                blocks.append((m.group(1), heading, [m.group(2)]))
            elif line.strip() and blocks:
                blocks[-1][2].append(line.strip())
        for number, title, lines in blocks:
            text = " ".join(" ".join(lines).split())
            if text:
                out.append(
                    PolicySection(
                        doc.doc_id,
                        number,
                        title,
                        text,
                        doc.title,
                        doc.fields["owner"],
                        doc.fields["entity"],
                    )
                )
    return out
