"""Evaluasi retrieval dan bantu menentukan SCORE_THRESHOLD.

    python -m eval.run_eval                       # retrieval saja, tanpa LLM (gratis)
    python -m eval.run_eval --csv eval/mine.csv   # pakai test set sendiri
    python -m eval.run_eval --llm                 # sekaligus jalankan pipeline penuh (memakai kuota Gemini)

Format CSV: question, answerable (yes/no), expected_title (substring judul), expected_keyword
(substring yang harus ada di salah satu chunk teratas).

Yang dilaporkan:
- hit@1 / hit@k : apakah chunk yang benar (judul + kata kunci) ada di peringkat 1 / top-k.
- Sebaran skor tertinggi untuk pertanyaan yang bisa dijawab vs yang tidak, plus saran ambang.
  Skor bergantung pada model embedding, jadi JALANKAN ULANG setiap kali model diganti.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

from app.config import get_settings
from app.db import init_db
from app.rag.embeddings import build_embedder
from app.rag.search import Retriever


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def suggest_threshold(answerable: list[float], unanswerable: list[float]) -> str:
    if not answerable or not unanswerable:
        return "Data kurang untuk menyarankan ambang (butuh kedua jenis pertanyaan)."
    low_ok, high_bad = min(answerable), max(unanswerable)
    if low_ok > high_bad:
        mid = round((low_ok + high_bad) / 2, 3)
        return f"Skor terpisah bersih. Saran SCORE_THRESHOLD = {mid} (antara {high_bad:.3f} dan {low_ok:.3f})."
    p10 = sorted(answerable)[max(0, int(len(answerable) * 0.1) - 1)] if len(answerable) > 1 else low_ok
    return (
        f"Skor tumpang tindih (terendah terjawab {low_ok:.3f} <= tertinggi tak-terjawab {high_bad:.3f}). "
        f"Ambang sekitar {round(max(high_bad, p10 - 0.02), 3)} adalah kompromi; tambah dokumen/uji lebih banyak "
        "atau andalkan lapisan guardrail LLM (TIDAK_DITEMUKAN)."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="eval/testset.csv")
    ap.add_argument("--llm", action="store_true", help="jalankan juga pipeline penuh dengan LLM")
    args = ap.parse_args()

    settings = get_settings()
    init_db()
    embedder = build_embedder(settings)
    retriever = Retriever(embedder, settings)
    pipeline = None
    if args.llm:
        from app.rag.llm import build_llm
        from app.rag.pipeline import Pipeline

        pipeline = Pipeline(retriever, build_llm(settings), settings)

    rows = load_rows(Path(args.csv))
    k = settings.top_k
    print(f"Embedding {embedder.name} | top_k={k} | ambang saat ini={settings.score_threshold}\n")

    hit1 = hitk = n_ans = 0
    ans_scores: list[float] = []
    no_scores: list[float] = []
    llm_ok = 0

    for r in rows:
        q = r["question"].strip()
        answerable = r["answerable"].strip().lower() == "yes"
        hits = retriever.search(q, top_k=k)
        top = hits[0].score if hits else 0.0
        mark = ""
        if answerable:
            n_ans += 1
            ans_scores.append(top)

            def is_match(h):
                return r["expected_title"].casefold() in h.doc_title.casefold() and \
                    r["expected_keyword"].casefold() in h.content.casefold()

            ranks = [i for i, h in enumerate(hits) if is_match(h)]
            if ranks:
                hitk += 1
                if ranks[0] == 0:
                    hit1 += 1
            mark = f"rank={ranks[0] + 1}" if ranks else "MELESET"
        else:
            no_scores.append(top)
            mark = "lolos ambang (seharusnya ditolak)" if top >= settings.score_threshold else "ditolak"

        extra = ""
        if pipeline:
            res = pipeline.ask(q, channel="eval")
            good = (res.status == "answered") == answerable
            llm_ok += int(good)
            extra = f" | llm={res.status}{'' if good else ' (SALAH)'}"
        print(f"[{'JAWAB' if answerable else 'TOLAK'}] skor={top:.3f} {mark}{extra} | {q}")

    print("\n--- Ringkasan ---")
    if n_ans:
        print(f"hit@1 = {hit1}/{n_ans} ({hit1 / n_ans:.0%}) | hit@{k} = {hitk}/{n_ans} ({hitk / n_ans:.0%})")
    if ans_scores:
        print(f"Skor tertinggi, bisa dijawab : min {min(ans_scores):.3f} | rata-rata {statistics.mean(ans_scores):.3f}")
    if no_scores:
        print(f"Skor tertinggi, tak terjawab : maks {max(no_scores):.3f} | rata-rata {statistics.mean(no_scores):.3f}")
    print(suggest_threshold(ans_scores, no_scores))
    if pipeline:
        print(f"Pipeline penuh benar: {llm_ok}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
