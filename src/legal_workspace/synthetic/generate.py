"""Generate synthetic matter PDFs plus the recorded ("gold") model outputs used by fixture mode and the evaluation."""

from __future__ import annotations

import argparse
import io
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from ..ingestion.extract import locate_quote
from ..ingestion.pdfio import parse_pdf
from ..ingestion.render import text_to_pdf
from ..ingestion.service import text_fingerprint
from .matters import available, load
from .spec import Doc, Matter


def _scanned_pdf(text: str) -> bytes:
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(text_to_pdf(text, footer=False))[0]
    img = page.render(scale=2.5).to_pil().convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=180.0)
    return buf.getvalue()


def classification_payload(m: Matter, d: Doc) -> dict[str, Any]:
    parties = [
        {"name": p.name, "role": p.role if d.suit_roles else "OTHER", "aliases": p.aliases} for p in m.parties
    ]
    return {
        "document_type": d.doc_type, "title": d.title, "document_date": d.date,
        "author": m.party(d.author).name if d.author else "", "parties": parties,
        "defined_terms": [{"term": t, "party": m.party(k).name} for t, k in d.terms],
        "signed_by_all_parties": d.signed, "amends": d.amends, "confidence": d.confidence,
    }  # fmt: skip


def render_matter(m: Matter) -> tuple[dict[str, bytes], dict[str, dict[str, Any]], dict[str, str]]:
    """(files by name, recorded model outputs, duplicate map) for a matter, entirely in memory."""
    fixtures: dict[str, dict[str, Any]] = {"classify": {}, "extract": {}}
    files: dict[str, bytes] = {}
    for d in m.docs:
        if d.is_duplicate_of:
            files[d.file] = files[d.is_duplicate_of]
            continue
        data = _scanned_pdf(d.text) if d.scanned else text_to_pdf(d.text, title=d.title)
        files[d.file] = data
        if d.no_fixture:
            continue
        pages, _ = parse_pdf(data)
        page_text = {p.number: p.text for p in pages}
        items = []
        for it in d.items:
            page = locate_quote(it.quote, page_text, 1, 90)
            if page is None:
                raise ValueError(f"{m.id}/{d.file}: quote not found in the rendered document: {it.quote!r}")
            items.append({
                "subject_type": it.subject_type, "subject_ref": it.subject_ref, "slot": it.slot, "value": it.value,
                "quote": it.quote, "page": page, "subject_date": it.subject_date, "subject_party": it.subject_party,
                "direction_kind": it.direction_kind,
            })  # fmt: skip
        payload = classification_payload(m, d)
        for k in (text_fingerprint(pages), f"file:{d.file}"):
            fixtures["classify"][k] = payload
            fixtures["extract"][k] = {"items": items}
    return files, fixtures, {d.file: d.is_duplicate_of for d in m.docs if d.is_duplicate_of}


def build_matter(m: Matter, out_dir: Path) -> dict[str, Any]:
    root = out_dir / "synthetic" / m.id
    if root.exists():
        shutil.rmtree(root)
    files, fixtures, _ = render_matter(m)
    manifest: dict[str, Any] = {"id": m.id, "number": m.number, "title": m.title, "type": m.matter_type, "forum": m.forum,
                                "description": m.description, "batches": {}}  # fmt: skip
    for d in m.docs:
        bdir = root / f"batch{d.batch}"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / d.file).write_bytes(files[d.file])
        manifest["batches"].setdefault(str(d.batch), []).append(
            {"file": d.file, "path": f"batch{d.batch}/{d.file}", "document_type": d.doc_type, "duplicate_of": d.is_duplicate_of or None,
             "scanned": d.scanned}
        )  # fmt: skip
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    (root / "golden.yaml").write_text(
        yaml.safe_dump([asdict(q) for q in m.questions], sort_keys=False, allow_unicode=True)
    )
    (root / "probes.yaml").write_text(
        yaml.safe_dump([asdict(p) for p in m.probes], sort_keys=False, allow_unicode=True)
    )
    (root / "planted.yaml").write_text(
        yaml.safe_dump([asdict(p) for p in m.planted], sort_keys=False, allow_unicode=True)
    )
    fx = out_dir / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    (fx / f"{m.id}.json").write_text(json.dumps(fixtures, indent=1, ensure_ascii=False))
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate synthetic matters (PDFs + recorded model outputs + golden set)"
    )
    ap.add_argument("--matters", nargs="*", default=None, help="e.g. M2 (default: all available)")
    ap.add_argument("--out", default="data", type=Path)
    args = ap.parse_args()
    for mid in args.matters or available():
        manifest = build_matter(load(mid), args.out)
        n = sum(len(v) for v in manifest["batches"].values())
        print(f"{mid}: {n} files in {len(manifest['batches'])} batch(es) -> {args.out}/synthetic/{mid}")


if __name__ == "__main__":
    main()
