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
