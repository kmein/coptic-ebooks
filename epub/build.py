#!/usr/bin/env python3
"""Build a bilingual Coptic/English EPUB 3 from one Coptic SCRIPTORIUM corpus.

Input is the TreeTagger SGML (*.tt) export, either as a `*_TT/` directory or a
`*_TT.zip` archive. Unlike the TEI export, it exists for every corpus and is a
flat token stream, so overlapping spans (translation, verse, bound group,
manuscript line, ...) never make it unparseable.
"""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent

ATTR = re.compile(r'([\w.:-]+)\s*=\s*"([^"]*)"')
TAG_NAME = re.compile(r"<([^\s>/]+)")
MARKUP = re.compile(r"<[^>]*>")
# Untranslated passages carry "..." (or similar) instead of a translation.
PLACEHOLDER = re.compile(r"^[\s.…\[\]?]*$")
# Bible corpora name documents like "01_Matthew_01" / "73_Epistle of Jeremiah_1".
BIBLE_TITLE = re.compile(r"^\d+_(.+?)_0*(\d+)$")
NATURAL = re.compile(r"(\d+)")
COPTIC_WORD = re.compile(r"^(?:[\u2c80-\u2ce4\u03e2-\u03ef][\u0300-\u036f\ufe20-\ufe2f\u1dc0-\u1dff\u2cef-\u2cf1\u2cff]*)+$")
EMPTY_META = {"", "none", "unknown", "anonymous", "na", "n/a"}

# Corpora whose metadata yields no good book title (no shared work title, or
# only manuscript-specific document titles).
TITLES = {
    "AP": "Apophthegmata Patrum",
    "besa-letters": "Letters of Besa",
    "bohairic-habakkuk": "Habakkuk",
    "bohairic.1corinthians": "1 Corinthians",
    "bohairic.mark": "The Gospel of Mark",
    "bohairic.nt": "The New Testament",
    "bohairic.ot": "The Old Testament",
    "book-bartholomew": "The Book of Bartholomew",
    "coptic-treebank": "Coptic Treebank",
    "doc-papyri": "Documentary Papyri",
    "helias": "The Encomium and Martyrdom of Helias",
    "life-paul-tamma": "The Life of Paul of Tamma",
    "magical-papyri": "Magical Papyri",
    "mercurius": "The Martyrdom, Miracles and Encomium of Mercurius",
    "proclus-homilies": "Homilies of Proclus",
    "pseudo-athanasius-discourses": "Discourses of Pseudo-Athanasius",
    "pseudo-chrysostom": "Homilies of Pseudo-Chrysostom",
    "pseudo-ephrem": "The Asceticon and a Letter of Pseudo-Ephrem",
    "pseudo-theophilus": "Homilies of Pseudo-Theophilus",
    "sahidic.ot": "The Old Testament",
    "sahidic.ruth": "Ruth",
    "sahidica.1corinthians": "1 Corinthians",
    "sahidica.mark": "The Gospel of Mark",
    "sahidica.nt": "The New Testament",
    "shenoute-eagerness": "I See Your Eagerness",
    "shenoute-errs": "If Everyone Errs",
    "shenoute-house": "This Great House",
    "shenoute-uncertain-xr": "Uncertain Canons",
}

# Upstream metadata errors.
AUTHORS = {
    "bohairic.mark": [],  # documents claim "Paul the apostle"
}

# Embedded fonts: (CLI option, file stem, CSS family, style, weight)
FACES = [
    ("coptic_font", "coptic", "Noto Sans Coptic", "normal", "normal"),
    ("serif_font", "serif", "Libertinus Serif", "normal", "normal"),
    ("serif_italic_font", "serif-italic", "Libertinus Serif", "italic", "normal"),
    ("serif_bold_font", "serif-bold", "Libertinus Serif", "normal", "bold"),
    ("fallback_font", "fallback", "DejaVu Sans", "normal", "normal"),
]


# ---------------------------------------------------------------- model


@dataclass
class Word:
    parts: list  # [(text, css class or "")]
    marker: str | None = None  # verse/section starting inside a segment


@dataclass
class Segment:
    """One translation unit: a run of Coptic words and its English rendering."""

    translation: str | None
    words: list = field(default_factory=list)
    label: str | None = None  # verse number shown in the gutter
    id: str = ""


@dataclass
class Section:
    label: str
    id: str


@dataclass
class Doc:
    name: str
    meta: dict
    items: list  # Segment | Section
    title: str = ""
    group: str | None = None
    file: str = ""
    tokens: int = 0
    translated: int = 0

    @property
    def sections(self):
        return [i for i in self.items if isinstance(i, Section)]


# ---------------------------------------------------------------- parsing


def tt_sources(corpus: Path):
    for d in sorted(corpus.glob("*_TT")):
        for f in sorted(d.glob("*.tt")):
            yield f.stem, f.read_text(encoding="utf-8")
    for z in sorted(corpus.glob("*_TT.zip")):
        with zipfile.ZipFile(z) as zf:
            for n in sorted(zf.namelist()):
                if n.endswith(".tt"):
                    yield Path(n).stem, zf.read(n).decode("utf-8")


def events(text):
    """Yield ("open", name, attrs) | ("close", name, None) | ("text", token, None)."""
    pending = None
    for line in text.split("\n"):
        s = line.strip()
        if pending is not None:  # tag continued over several lines
            pending += " " + s
            if not s.endswith(">"):
                continue
            s, pending = pending, None
        elif s.startswith("<") and not s.endswith(">"):
            pending = s
            continue
        if not s:
            continue
        if s.startswith("</"):
            yield "close", s[2:-1].strip(), None
        elif s.startswith("<"):
            m = TAG_NAME.match(s)
            attrs = {k: html.unescape(v) for k, v in ATTR.findall(s[m.end():])}
            yield "open", m.group(1), attrs
        else:
            yield "text", s, None


def clean(s):
    return " ".join(MARKUP.sub("", s or "").split())


def verse_label(v):
    return v.rsplit(":", 1)[-1].strip()


def rend_class(stack):
    rends = " ".join(stack)
    cls = []
    if "red" in rends:
        cls.append("rb")
    if "large" in rends or "tall" in rends:
        cls.append("big")
    if "superscript" in rends:
        cls.append("sup")
    elif "subscript" in rends:
        cls.append("sub")
    return " ".join(cls)


def parse_doc(name, text):
    evs = list(events(text))
    meta = next((a for k, n, a in evs if k == "open" and n == "meta"), {})
    tags = {n for k, n, _ in evs if k == "open"}
    # Diplomatic bound groups keep supralinear strokes, punctuation and
    # editorial brackets; some Bible corpora only have normalized groups.
    group_tag = next((t for t in ("orig_group", "norm_group") if t in tags), None)
    verse_tag = "verse_n" if "verse_n" in tags else None
    if verse_tag is None and "chapter_n" not in tags and "p_n" in tags:
        verse_tag = "p_n"

    doc = Doc(name, meta, [])
    seg = word = None
    pending_verse = pending_section = None
    rend = []
    n_seg = n_sec = 0

    def finish():
        nonlocal seg, word
        if seg is not None and not seg.words and seg.translation:
            seg.id = f"v{n_seg}"
            doc.items.append(seg)
        seg = word = None

    for kind, n, a in evs:
        if kind == "open":
            if n == "translation":
                finish()
                t = clean(a.get("translation"))
                seg = Segment(None if PLACEHOLDER.match(t) else t)
                n_seg += 1
            elif n == group_tag:
                word = None
            elif n in (verse_tag, "chapter_n"):
                # Untranslated text has no translation spans to divide it.
                if seg is not None and seg.translation is None and seg.words:
                    finish()
                if n == verse_tag:
                    pending_verse = verse_label(a.get(n, ""))
                else:
                    pending_section = a.get(n, "").strip()
            elif n == "hi_rend":
                rend.append(a.get(n, ""))
        elif kind == "close":
            if n == "translation":
                finish()
            elif n == group_tag:
                word = None
            elif n == "hi_rend" and rend:
                rend.pop()
        else:
            if seg is None:
                seg = Segment(None)
                n_seg += 1
            doc.tokens += 1
            doc.translated += seg.translation is not None
            if not seg.words:
                if pending_section:
                    n_sec += 1
                    doc.items.append(Section(pending_section, f"s{n_sec}"))
                    pending_section = None
                seg.id = f"v{n_seg}"
                doc.items.append(seg)
            if word is None:
                word = Word([])
                if pending_section:  # section starts mid-sentence
                    word.marker = f"§{pending_section}"
                    pending_section = None
                if pending_verse:
                    if not seg.words:
                        seg.label = pending_verse
                    else:
                        word.marker = pending_verse
                    pending_verse = None
                seg.words.append(word)
            word.parts.append((n, rend_class(rend)))
            if group_tag is None:
                word = None
    finish()
    if len(doc.sections) == 1:  # a lone "§ 1" adds nothing
        doc.items = [i for i in doc.items if not isinstance(i, Section)]

    title = meta.get("title", name).strip()
    m = BIBLE_TITLE.match(title)
    if m:
        doc.group = m.group(1).replace("_", " ")
        doc.title = f"{doc.group} {m.group(2)}"
    else:
        doc.title = title
        doc.group = (meta.get("msItem_title") or "").strip() or None
    return doc


def natural_key(s):
    return [int(p) if p.isdigit() else p.lower() for p in NATURAL.split(s)]


def order(docs):
    """Follow the next/previous CTS links; unlinked documents sort naturally."""
    by_urn = {d.meta.get("document_cts_urn"): d for d in docs}
    nxt = {}
    for d in docs:
        urn = d.meta.get("document_cts_urn")
        if d.meta.get("next") in by_urn and d.meta["next"] != urn:
            nxt.setdefault(urn, d.meta["next"])
        if d.meta.get("previous") in by_urn and d.meta["previous"] != urn:
            nxt.setdefault(d.meta["previous"], urn)
    has_prev = set(nxt.values())
    heads = sorted((d for d in docs if d.meta.get("document_cts_urn") not in has_prev),
                   key=lambda d: natural_key(d.name))
    out, seen = [], set()
    for d in heads + sorted(docs, key=lambda d: natural_key(d.name)):
        while d is not None and id(d) not in seen:
            seen.add(id(d))
            out.append(d)
            d = by_urn.get(nxt.get(d.meta.get("document_cts_urn")))
    return out


# ---------------------------------------------------------------- book


def uniq(values):
    out = []
    for v in values:
        v = clean(v)
        if v.lower() not in EMPTY_META and v not in out:
            out.append(v)
    return out


def joined(values, limit=6):
    values = uniq(values)
    if len(values) > limit:
        return "; ".join(values[:limit]) + "; …"
    return "; ".join(values)


def short_title(title, prefixes):
    """'Apophthegmata Patrum Sahidic 001: …' → 'Sahidic 001: …' inside that book.

    Prefixes match fuzzily, since upstream titles contain typos
    ('Apopthegmata', 'Acephelous')."""
    for p in sorted((clean(p) for p in prefixes), key=len, reverse=True):
        for cut in range(max(1, len(p) - 2), len(p) + 3) if p else ():  # typos change the length
            if cut >= len(title) - 2 or title[cut] not in " :;,–—":
                continue
            if SequenceMatcher(None, title[:cut].lower(), p.lower()).ratio() >= 0.9:
                rest = title[cut:].lstrip(" :;,.-–—")
                # "(Budge ed.) Part 1" means nothing without the work title
                if len(rest) >= 3 and not rest.startswith("("):
                    return rest[0].upper() + rest[1:]
                return title
    return title


class Book:
    def __init__(self, corpus: Path, docs):
        self.slug = corpus.name
        self.docs = order(docs)
        metas = [d.meta for d in self.docs]
        works = Counter(clean(m.get("msItem_title", "")) for m in metas)
        work, n_work = works.most_common(1)[0]
        if self.slug in TITLES:
            self.title = TITLES[self.slug]
        elif work and n_work * 2 > len(metas):
            self.title = work
        elif len(self.docs) == 1:
            self.title = self.docs[0].title
        else:
            self.title = self.slug.replace("-", " ").replace(".", " ").title()
        langs = Counter(clean(m.get("language", "")) for m in metas if m.get("language"))
        self.dialect = (langs.most_common(1)[0][0] if langs else
                        "Bohairic Coptic" if "bohairic" in self.slug else "Sahidic Coptic")
        self.authors = AUTHORS.get(self.slug, uniq(m.get("author", "") for m in metas))
        self.licenses = uniq(m.get("license", "") for m in metas)
        self.version = max((m.get("version_date", "") for m in metas), default="") or "2000-01-01"
        tokens = sum(d.tokens for d in self.docs)
        self.coverage = sum(d.translated for d in self.docs) / tokens if tokens else 0
        self.translators = uniq(m.get("translation", "") for m in metas) if self.coverage else []
        groups = [d.group for d in self.docs]
        runs = [g for i, g in enumerate(groups) if i == 0 or groups[i - 1] != g]
        # Group the contents by work only when works form contiguous runs and
        # some work spans several documents; inconsistent metadata (typos,
        # missing titles) falls back to a flat list.
        self.grouped = (None not in runs and len(runs) == len(set(runs))
                        and len(runs) < len(groups) and len(runs) > 1)
        self.numbered = any(isinstance(i, Segment) and i.label for d in self.docs for i in d.items)
        self.id = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL,
                                               f"https://github.com/CopticScriptorium/corpora/{self.slug}"))
        for i, d in enumerate(self.docs, 1):
            d.file = f"d{i:04}.xhtml"
            if len(self.docs) > 1:
                d.title = short_title(d.title, (self.title, d.group if self.grouped else ""))

    @property
    def subtitle(self):
        if self.coverage == 0:
            return f"{self.dialect} text"
        return f"{self.dialect} text with English translation"

    def incipit(self, n=4):
        words = []
        for d in self.docs:
            for seg in d.items:
                if not isinstance(seg, Segment):
                    continue
                for w in seg.words:
                    t = "".join(p for p, _ in w.parts)
                    if COPTIC_WORD.match(t):
                        words.append(t)
                        if len(words) == n:
                            return " ".join(words)
        return " ".join(words)


# ---------------------------------------------------------------- xhtml


def esc(s):
    return html.escape(s, quote=True)


def page(title, body, body_class=""):
    cls = f' class="{body_class}"' if body_class else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
<meta charset="utf-8"/>
<title>{esc(title)}</title>
<link rel="stylesheet" type="text/css" href="../css/book.css"/>
</head>
<body{cls}>
{body}
</body>
</html>
"""


def render_word(w):
    out = []
    if w.marker:
        out.append(f'<span class="vm">{esc(w.marker)}</span>')
    runs = []
    for text, cls in w.parts:
        if runs and runs[-1][1] == cls:
            runs[-1][0] += text
        else:
            runs.append([text, cls])
    for text, cls in runs:
        out.append(f'<span class="{cls}">{esc(text)}</span>' if cls else esc(text))
    return "".join(out)


COP = 'lang="cop" xml:lang="cop"'
# Punctuation and editorial brackets annotated as bound groups of their own:
# set them against the neighbouring word, as printed editions do.
CLOSING = re.compile(r"^(?:[,;:·\u0387\u2027\u2cf9-\u2cfe\u2056\u2058\u205b\u205d\u205e\u2e31\])⟧⟩〉⸣]|\.(?!\.))+$")
OPENING = re.compile(r"^[\[(⟦⟨〈⸢]+$")


def render_words(words):
    out = []
    prefix = ""
    for w in words:
        text = "".join(p for p, _ in w.parts)
        if OPENING.match(text) and not w.marker:
            prefix += render_word(w)
        elif out and not prefix and not w.marker and CLOSING.match(text):
            out[-1] += render_word(w)
        else:
            out.append(prefix + render_word(w))
            prefix = ""
    if prefix:
        out.append(prefix)
    return " ".join(out)


def render_segment(seg, numbered):
    parts = [f'<div class="seg" id="{seg.id}">']
    if seg.words:
        vn = ""
        if numbered:
            vn = f'<span class="vn">{esc(seg.label or "")}</span>'
        parts.append(f'<p class="cop" {COP}>{vn}{render_words(seg.words)}</p>')
    if seg.translation:
        parts.append(f'<p class="tr">{esc(seg.translation)}</p>')
    parts.append("</div>")
    return "".join(parts)


def render_doc(book, doc, first_in_group):
    level = 2 if book.grouped else 1
    head = []
    if book.grouped and first_in_group:
        head.append(f'<h1 class="part">{esc(doc.group)}</h1>')
    head.append(f'<h{level} class="doc">{esc(doc.title)}</h{level}>')
    body = [f'<section epub:type="chapter" role="doc-chapter">', "<header>", *head, "</header>"]
    for item in doc.items:
        if isinstance(item, Section):
            body.append(f'<h{level + 1} class="sec" id="{item.id}">§ {esc(item.label)}</h{level + 1}>')
        else:
            body.append(render_segment(item, book.numbered))
    body.append("</section>")
    return page(doc.title, "\n".join(body), "num" if book.numbered else "")


def render_cover():
    return page("Cover", """<section epub:type="cover" class="cover">
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1"
 viewBox="0 0 1600 2560" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
<image width="1600" height="2560" xlink:href="../images/cover.png"/>
</svg>
</section>""", "cover")


def render_title(book):
    lines = ['<section epub:type="titlepage" class="titlepage">']
    incipit = book.incipit()
    if incipit:
        lines.append(f'<p class="incipit" {COP}>{esc(incipit)}</p>')
    lines.append(f'<h1 class="book-title">{esc(book.title)}</h1>')
    if book.authors:
        lines.append(f'<p class="book-author">{esc(joined(book.authors, 3))}</p>')
    lines.append(f'<p class="book-sub">{esc(book.subtitle)}</p>')
    lines.append('<hr class="rule"/>')
    credits = []
    if book.translators:
        credits.append(("Translation", joined(book.translators, 4)))
    credits.append(("Edition and annotation", "Coptic SCRIPTORIUM"))
    if book.licenses:
        credits.append(("License", joined(book.licenses)))
    credits.append(("Data version", book.version))
    lines.append('<dl class="credits">')
    for k, v in credits:
        lines.append(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>")
    lines.append("</dl>")
    if 0 < book.coverage < 0.9:
        lines.append(f'<p class="note">The source data provides an English translation for about '
                     f"{round(book.coverage * 100)}% of the text; untranslated passages appear in Coptic only.</p>")
    elif book.coverage == 0:
        lines.append('<p class="note">The source data does not yet provide an English translation '
                     "for this text.</p>")
    lines.append("</section>")
    return page(book.title, "\n".join(lines), "front")


SOURCE_FIELDS = [
    ("Author", ("author",)),
    ("Manuscript", ("msName",)),
    ("Repository", ("repository",)),
    ("Origin", ("origPlace",)),
    ("Date", ("origDate",)),
    ("Edition", ("Coptic_edition",)),
    ("Source", ("source",)),
    ("Translation", ("translation",)),
    ("Annotation", ("annotation",)),
    ("License", ("license",)),
    ("Version", ("version_n",)),
]


def render_sources(book):
    blocks = []
    for name, docs in groups(book):
        metas = [d.meta for d in docs]
        rows = []
        for label, keys in SOURCE_FIELDS:
            v = joined(m.get(k, "") for m in metas for k in keys)
            if v:
                rows.append(f"<dt>{esc(label)}</dt><dd>{esc(v)}</dd>")
        urns = uniq(m.get("document_cts_urn", "") for m in metas)
        if len(urns) == 1:
            rows.append(f'<dt>CTS URN</dt><dd class="urn">{esc(urns[0])}</dd>')
        title = name or (book.title if len(book.docs) > 1 else docs[0].title)
        blocks.append(f'<h2>{esc(title)}</h2>\n<dl class="sources">{"".join(rows)}</dl>')
    body = f"""<section epub:type="appendix" role="doc-appendix" class="back">
<h1 class="doc">Sources and Credits</h1>
<p>Coptic text, linguistic annotation and translations come from the
<a href="https://copticscriptorium.org/">Coptic SCRIPTORIUM</a> corpora
(<a href="https://github.com/CopticScriptorium/corpora">github.com/CopticScriptorium/corpora</a>).
The Coptic is shown in diplomatic form: bound groups as segmented by the annotators, with
the manuscript’s supralinear strokes, punctuation and editorial brackets.</p>
{chr(10).join(blocks)}
</section>"""
    return page("Sources and Credits", body, "back")


def groups(book):
    """Consecutive documents sharing a work (or Bible book)."""
    out = []
    for d in book.docs:
        key = d.group if book.grouped else None
        if out and out[-1][0] == key:
            out[-1][1].append(d)
        else:
            out.append((key, [d]))
    if not book.grouped and len(book.docs) > 1:
        # One work split into parts: credit each part.
        return [(d.title, [d]) for d in book.docs] if len(book.docs) <= 12 else out
    return out


def toc_tree(book):
    """[(label, href, children)] shared by nav.xhtml and toc.ncx."""

    def doc_entry(d):
        kids = [(f"§ {s.label}", f"text/{d.file}#{s.id}", []) for s in d.sections]
        return (d.title, f"text/{d.file}", kids)

    tree = []
    if book.grouped:
        for name, docs in groups(book):
            if len(docs) == 1:
                tree.append(doc_entry(docs[0]))
            else:
                tree.append((name, f"text/{docs[0].file}", [doc_entry(d) for d in docs]))
    else:
        tree = [doc_entry(d) for d in book.docs]
        if len(tree) == 1:  # single document: list its sections directly
            tree = [(book.docs[0].title, tree[0][1], [])] + tree[0][2]
    tree.append(("Sources and Credits", "text/sources.xhtml", []))
    return tree


def render_nav(book, tree):
    def ol(items, depth):
        pad = "  " * depth
        out = [f"{pad}<ol>"]
        for label, href, kids in items:
            out.append(f'{pad}  <li><a href="{esc(href)}">{esc(label)}</a>')
            if kids:
                out.append(ol(kids, depth + 2))
            out.append(f"{pad}  </li>")
        out.append(f"{pad}</ol>")
        return "\n".join(out)

    first = book.docs[0].file
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
<meta charset="utf-8"/>
<title>Contents</title>
<link rel="stylesheet" type="text/css" href="css/book.css"/>
</head>
<body class="toc">
<nav epub:type="toc" id="toc" role="doc-toc">
<h1 class="doc">Contents</h1>
{ol(tree, 0)}
</nav>
<nav epub:type="landmarks" id="landmarks" hidden="hidden">
<ol>
  <li><a epub:type="cover" href="text/cover.xhtml">Cover</a></li>
  <li><a epub:type="titlepage" href="text/title.xhtml">Title Page</a></li>
  <li><a epub:type="toc" href="nav.xhtml">Contents</a></li>
  <li><a epub:type="bodymatter" href="text/{first}">Text</a></li>
  <li><a epub:type="backmatter" href="text/sources.xhtml">Sources and Credits</a></li>
</ol>
</nav>
</body>
</html>
"""


def render_ncx(book, tree):
    ids, orders = [0], {}  # NCX requires one playOrder per target

    def points(items, depth):
        out = []
        for label, href, kids in items:
            ids[0] += 1
            n = orders.setdefault(href, len(orders) + 1)
            pad = "  " * depth
            out.append(f'{pad}<navPoint id="np{ids[0]}" playOrder="{n}"><navLabel><text>{esc(label)}</text>'
                       f'</navLabel><content src="{esc(href)}"/>')
            out.extend(points(kids, depth + 1))
            out.append(f"{pad}</navPoint>")
        return out

    body = "\n".join(points(tree, 1))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="en">
<head><meta name="dtb:uid" content="{book.id}"/></head>
<docTitle><text>{esc(book.title)}</text></docTitle>
<navMap>
{body}
</navMap>
</ncx>
"""


def render_opf(book, manifest, spine):
    meta = [
        f'<dc:identifier id="bookid">{book.id}</dc:identifier>',
        f"<dc:title>{esc(book.title)}</dc:title>",
        "<dc:language>en</dc:language>",
        "<dc:language>cop</dc:language>",
        f'<meta property="dcterms:modified">{book.version}T00:00:00Z</meta>',
        f"<dc:date>{book.version}</dc:date>",
        f"<dc:description>{esc(book.subtitle)}, from the Coptic SCRIPTORIUM corpora.</dc:description>",
        "<dc:publisher>Coptic SCRIPTORIUM</dc:publisher>",
        "<dc:source>https://github.com/CopticScriptorium/corpora</dc:source>",
        "<dc:subject>Coptic literature</dc:subject>",
        '<meta name="cover" content="cover-image"/>',
    ]
    for i, a in enumerate(book.authors[:3]):
        meta.append(f'<dc:creator id="aut{i}">{esc(a)}</dc:creator>')
        meta.append(f'<meta refines="#aut{i}" property="role" scheme="marc:relators">aut</meta>')
    for i, t in enumerate(book.translators[:4]):
        meta.append(f'<dc:contributor id="trl{i}">{esc(t)}</dc:contributor>')
        meta.append(f'<meta refines="#trl{i}" property="role" scheme="marc:relators">trl</meta>')
    if book.licenses:
        meta.append(f"<dc:rights>{esc(joined(book.licenses))}</dc:rights>")
    items = "\n    ".join(
        f'<item id="{i}" href="{esc(h)}" media-type="{t}"' + (f' properties="{p}"' if p else "") + "/>"
        for i, h, t, p in manifest)
    refs = "\n    ".join(f'<itemref idref="{i}"/>' for i in spine)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    {chr(10).join("    " + m for m in meta).strip()}
  </metadata>
  <manifest>
    {items}
  </manifest>
  <spine toc="ncx">
    {refs}
  </spine>
</package>
"""


CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


# ---------------------------------------------------------------- assets


def subset_font(src: Path, text: str) -> bytes:
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    font = subset.load_font(str(src), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)
    with tempfile.NamedTemporaryFile(suffix=src.suffix) as tmp:
        subset.save_font(font, tmp.name, opts)
        return Path(tmp.name).read_bytes()


def make_cover(book, typst: str, font_dirs: list[str]) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copy(HERE / "cover.typ", tmp / "cover.typ")
        (tmp / "cover.json").write_text(json.dumps({
            "title": book.title,
            "author": joined(book.authors, 2),
            "subtitle": book.subtitle,
            "incipit": book.incipit(3),
        }), encoding="utf-8")
        cmd = [typst, "compile", "--format", "png", "--ppi", "256", "--ignore-system-fonts"]
        for d in font_dirs:
            cmd += ["--font-path", d]
        subprocess.run(cmd + [str(tmp / "cover.typ"), str(tmp / "cover.png")], check=True)
        return (tmp / "cover.png").read_bytes()


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus", type=Path, help="corpus directory, e.g. corpora/shenoute-fox")
    ap.add_argument("output", type=Path)
    for arg, _, family, _, _ in FACES:
        ap.add_argument(f"--{arg.replace('_', '-')}", type=Path, required=True, help=f"{family} font file")
    ap.add_argument("--typst", default="typst")
    args = ap.parse_args()

    docs = [parse_doc(name, text) for name, text in tt_sources(args.corpus)]
    docs = [d for d in docs if d.tokens]
    if not docs:
        sys.exit(f"{args.corpus}: no TreeTagger (*_TT) documents")
    book = Book(args.corpus, docs)

    pages = {"cover.xhtml": render_cover(), "title.xhtml": render_title(book)}
    # Part heading before the first document of each multi-document work.
    first_of = {id(ds[0]) for _, ds in groups(book) if len(ds) > 1} if book.grouped else set()
    for d in book.docs:
        pages[d.file] = render_doc(book, d, id(d) in first_of)
    pages["sources.xhtml"] = render_sources(book)
    tree = toc_tree(book)
    nav = render_nav(book, tree)

    coptic_text = "".join(p for d in book.docs for s in d.items if isinstance(s, Segment)
                          for w in s.words for p, _ in w.parts) + book.incipit()
    all_text = "".join(MARKUP.sub("", html.unescape(p)) for p in [*pages.values(), nav]) + "§–—’“”…"
    covered = set()
    for arg in ("coptic_font", "serif_font"):
        covered |= set(TTFont(getattr(args, arg)).getBestCmap())
    texts = {
        "coptic": coptic_text,
        "serif": all_text,
        "serif-italic": all_text,
        "serif-bold": all_text,
        # rare manuscript signs (⁛ ◈ ❮ …) missing from both text fonts
        "fallback": "".join(sorted({c for c in all_text if ord(c) not in covered and not c.isspace()})),
    }
    font_files, faces = {}, []
    for arg, key, family, style, weight in FACES:
        if not texts[key]:
            continue
        src = getattr(args, arg)
        name = f"{key}{src.suffix}"
        font_files[name] = subset_font(src, texts[key])
        faces.append(f'@font-face {{\n  font-family: "{family}";\n  font-style: {style};\n'
                     f'  font-weight: {weight};\n  src: url("../fonts/{name}");\n}}\n')
    cover = make_cover(book, args.typst, sorted({str(args.coptic_font.parent), str(args.serif_font.parent)}))
    css = "\n".join(faces) + "\n" + (HERE / "style.css").read_text(encoding="utf-8")

    def font_type(name):
        return "font/otf" if name.endswith(".otf") else "font/ttf"

    manifest = [
        ("ncx", "toc.ncx", "application/x-dtbncx+xml", ""),
        ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
        ("css", "css/book.css", "text/css", ""),
        ("cover-image", "images/cover.png", "image/png", "cover-image"),
        *((f"font{i}", f"fonts/{n}", font_type(n), "") for i, n in enumerate(font_files)),
        *((Path(n).stem, f"text/{n}", "application/xhtml+xml", "svg" if n == "cover.xhtml" else "")
          for n in pages),
    ]
    spine = ["cover", "title", "nav", *(Path(d.file).stem for d in book.docs), "sources"]

    entries = {
        "META-INF/container.xml": CONTAINER,
        "OEBPS/content.opf": render_opf(book, manifest, spine),
        "OEBPS/nav.xhtml": nav,
        "OEBPS/toc.ncx": render_ncx(book, tree),
        "OEBPS/css/book.css": css,
        "OEBPS/images/cover.png": cover,
        **{f"OEBPS/fonts/{n}": b for n, b in font_files.items()},
        **{f"OEBPS/text/{n}": p for n, p in pages.items()},
    }
    stamp = (1980, 1, 1, 0, 0, 0)  # reproducible archives
    with zipfile.ZipFile(args.output, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype", stamp), "application/epub+zip", zipfile.ZIP_STORED)
        for name, data in entries.items():
            zf.writestr(zipfile.ZipInfo(name, stamp), data, zipfile.ZIP_DEFLATED)


if __name__ == "__main__":
    main()
