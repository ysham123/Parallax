"""Role-scoped context packets.

Every provider call receives a packet compiled from durable run state. A packet
holds only the sections its compiler names, in a fixed order, each clipped to a
character budget. If the whole packet still exceeds the provider's prompt limit,
sections are trimmed lowest priority first; mandatory sections (the request,
the task, a variant directive) are never cut. Transcripts are never replayed:
state persists, conversations do not.

Each section is fenced with a hash of its own text, so project or model text
inside a section cannot impersonate another section. The manifest records names,
sizes and SHA-256 hashes, never content, so a run can show what each agent was
given without mirroring it.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from .providers import MAX_PROMPT

PROMPT_LIMIT = MAX_PROMPT - 1000
REQUEST_LIMIT = 150_000
MANDATORY = 100
MANIFEST_VERSION = 1


def render_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def clip(text: str, budget: int) -> tuple[str, int]:
    """Keep the first `budget` characters, marking how many were cut."""
    if len(text) <= budget:
        return text, 0
    marker = "\n[... {} chars omitted]"
    keep = max(0, budget - len(marker.format(len(text))))
    return text[:keep] + marker.format(len(text) - keep), len(text) - keep


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


@dataclass(frozen=True)
class Section:
    name: str
    body: object
    budget: int = 8000
    priority: int = 50  # lower is trimmed first; MANDATORY is never trimmed


@dataclass
class Packet:
    role: str
    preamble: str
    sections: list = field(default_factory=list)
    task_id: str | None = None
    limit: int = PROMPT_LIMIT
    _cache: tuple | None = field(default=None, init=False, repr=False, compare=False)

    def _layout(self) -> tuple[str, list[dict]]:
        if self._cache is not None:
            return self._cache
        parts = []
        for section in self.sections:
            if section.body in (None, "", [], {}, ()):
                continue
            text = section.body if isinstance(section.body, str) else render_json(section.body)
            budget = len(text) if section.priority >= MANDATORY else section.budget
            clipped, cut = clip(text, budget)
            parts.append({"section": section, "text": clipped, "cut": cut, "full": len(text)})

        def fenced(part):
            name, text = part["section"].name, part["text"]
            tag = _sha(text)[:8]
            return f"### {name}\n<<<begin {name} {tag}>>>\n{text}\n<<<end {name} {tag}>>>"

        def total():
            return len(self.preamble) + sum(len(fenced(p)) + 2 for p in parts)

        overflow = total() - self.limit
        # Trim the least important sections first; within a priority, later (more volatile) sections go first.
        order = sorted((p for p in parts if p["section"].priority < MANDATORY),
                       key=lambda p: (p["section"].priority, -parts.index(p)))
        for part in order:
            if overflow <= 0:
                break
            room = len(part["text"]) - overflow
            if room > 200:
                original = part["text"]
                part["text"], extra = clip(original, room)
                part["cut"] += extra
            else:
                part["cut"] = part["full"]
                part["text"] = ""
            overflow = total() - self.limit
        parts = [p for p in parts if p["text"]]
        if total() > self.limit:
            raise ValueError("Context packet exceeds the provider prompt limit")
        prompt = "\n\n".join([self.preamble.strip(), *(fenced(p) for p in parts)])
        self._cache = (prompt, parts)
        return self._cache

    def render(self) -> str:
        return self._layout()[0]

    def manifest(self) -> dict:
        prompt, parts = self._layout()
        sections = [{"name": p["section"].name, "chars": len(p["text"]), "sha256": _sha(p["text"]),
                     "truncated_chars": p["cut"]} for p in parts]
        return {"v": MANIFEST_VERSION, "role": self.role, "task_id": self.task_id, "chars": len(prompt), "sha256": _sha(prompt),
                "sections": sections, "message": f"Context packet · {len(sections)} sections · {len(prompt):,} chars"}


# Patch helpers ---------------------------------------------------------------

def split_patch(diff: str) -> list[tuple[str, str]]:
    """Split a unified diff into (path, text) per file, keeping each file's header."""
    files, current, path = [], [], None
    for line in (diff or "").splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                files.append((path, "".join(current)))
            current = [line]
            head = line.rstrip("\n")[len("diff --git "):]
            path = head.split(" b/", 1)[1] if " b/" in head else head
        elif current:
            current.append(line)
    if current:
        files.append((path, "".join(current)))
    return files


def diffstat(diff: str) -> list[dict]:
    stats = []
    for path, text in split_patch(diff):
        added = removed = 0
        binary = False
        for line in text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
            elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
                binary = True
        stats.append({"file": path, "added": added, "removed": removed, "binary": binary})
    return stats


def filter_patch(diff: str, keep) -> str:
    return "".join(text for path, text in split_patch(diff) if keep(path))


def fit_patch(diff: str, budget: int) -> str:
    """Fit a patch into `budget` characters while keeping every file's header.

    Files share the budget round-robin, so one large file cannot hide the others.
    """
    if len(diff or "") <= budget:
        return diff or ""
    files = split_patch(diff)
    if not files:
        return clip(diff, budget)[0]
    headers = []
    for path, text in files:
        prefix = []
        for line in text.splitlines(keepends=True)[:6]:
            if line.startswith("@@"):
                break
            prefix.append(line)
        header = "".join(prefix)
        headers.append((header, text[len(header):]))
    remaining = budget - sum(len(h) for h, _ in headers) - 40 * len(files)
    if remaining <= 0:
        return "".join(h + "[... file body omitted]\n" for h, _ in headers)[:budget]
    shares = [0] * len(files)
    needs = [len(body) for _, body in headers]
    while remaining > 0:
        open_files = [i for i, need in enumerate(needs) if shares[i] < need]
        if not open_files:
            break
        portion = max(1, remaining // len(open_files))
        for i in open_files:
            grant = min(portion, needs[i] - shares[i], remaining)
            shares[i] += grant
            remaining -= grant
            if remaining <= 0:
                break
    out = []
    for (header, body), share in zip(headers, shares):
        out.append(header + (body if share >= len(body) else body[:share] + f"\n[... {len(body) - share} chars of this file omitted]\n"))
    return "".join(out)


def findings(values, limit: int = 8, each: int = 600) -> list[str]:
    """Normalize reviewer findings, which may be strings or structured objects."""
    out = []
    for value in (values or [])[:limit]:
        text = value if isinstance(value, str) else render_json(value)
        out.append(clip(text, each)[0])
    return out
