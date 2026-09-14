from __future__ import annotations

from typing import Any

from .db import TrainingDatabase
from .table_cell_ground_truth import ground_truth_review_state, load_table_cell_ground_truth


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator > 0 else 0.0


def _empty_source(source_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "candidate_total": 0,
        "reviewed": 0,
        "pending": 0,
        "correct": 0,
        "adjusted": 0,
        "rejected": 0,
        "irrelevant": 0,
        "irrelevant_correct": 0,
        "irrelevant_adjusted": 0,
        "added": 0,
        "reconstructed": 0,
        "manual_added": 0,
        "detected_desired": 0,
        "desired_total": 0,
        "direct_coverage": 0.0,
        "structural_coverage": 0.0,
        "reconstruction_rate": 0.0,
        "exact_box_rate": 0.0,
        "adjustment_rate": 0.0,
        "false_candidate_rate": 0.0,
        "fallback_need": 0.0,
        "review_completed": False,
    }


def _finalize_source(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    item["pending"] = max(0, int(item["candidate_total"]) - int(item["reviewed"]))
    relevant_correct = max(0, int(item["correct"]) - int(item["irrelevant_correct"]))
    relevant_adjusted = max(0, int(item["adjusted"]) - int(item["irrelevant_adjusted"]))
    item["detected_desired"] = relevant_correct + relevant_adjusted
    item["desired_total"] = int(item["detected_desired"]) + int(item["added"])
    item["direct_coverage"] = _ratio(item["detected_desired"], item["desired_total"])
    item["structural_coverage"] = _ratio(int(item["detected_desired"]) + int(item["reconstructed"]), item["desired_total"])
    item["reconstruction_rate"] = _ratio(item["reconstructed"], item["desired_total"])
    item["exact_box_rate"] = _ratio(relevant_correct, item["desired_total"])
    item["adjustment_rate"] = _ratio(relevant_adjusted, item["detected_desired"])
    item["false_candidate_rate"] = _ratio(item["rejected"], item["candidate_total"])
    item["fallback_need"] = _ratio(item["manual_added"], item["desired_total"])
    return item


def table_first_quality(
    db: TrainingDatabase,
    *,
    minimum_direct_coverage: float = 0.95,
    maximum_false_candidate_rate: float = 0.10,
    maximum_adjustment_rate: float = 0.25,
) -> dict[str, Any]:
    """Report table-cell quality and expose the authoritative table-first gate.

    Before canonical table-cell Ground Truth exists, the historic PP-Structure
    review metrics remain the gate. Once canonical GT exists, that persistent GT
    becomes authoritative: Mapping may continue when GT exists, contains cells,
    and every GT source is explicitly complete. Detector precision/FP/adjustment
    metrics remain diagnostic only and may no longer close Pipeline B.
    """
    rows = db.table_first_quality_rows()
    source_rows = rows["source_rows"]
    source_ids = [str(row["source_id"]) for row in source_rows]
    candidate_rows = rows["candidate_rows"]
    review_rows = rows["review_rows"]
    added_rows = rows["added_rows"]

    by_source = {source_id: _empty_source(source_id) for source_id in source_ids}
    for row in source_rows:
        by_source[str(row["source_id"])]["review_completed"] = bool(row["review_completed"])
    for row in candidate_rows:
        source_id = str(row["source_id"])
        by_source.setdefault(source_id, _empty_source(source_id))["candidate_total"] = int(row["amount"])
    for row in review_rows:
        source_id = str(row["source_id"])
        item = by_source.setdefault(source_id, _empty_source(source_id))
        status = str(row["review_status"] or "")
        relevance = str(row["relevance_status"] or "relevant")
        amount = int(row["amount"])
        if status in {"correct", "adjusted", "rejected"}:
            item["reviewed"] += amount
        if status == "correct":
            item["correct"] += amount
        elif status == "adjusted":
            item["adjusted"] += amount
        elif status == "rejected":
            item["rejected"] += amount
        if status in {"correct", "adjusted"} and relevance == "irrelevant":
            item["irrelevant"] += amount
            item[f"irrelevant_{status}"] += amount
    for row in added_rows:
        source_id = str(row["source_id"])
        item = by_source.setdefault(source_id, _empty_source(source_id))
        item["added"] = int(row["amount"])
        item["reconstructed"] = int(row["reconstructed"] or 0)
        item["manual_added"] = max(0, item["added"] - item["reconstructed"])

    sources = [_finalize_source(by_source[source_id]) for source_id in sorted(by_source)]
    totals = {
        key: sum(int(item[key]) for item in sources)
        for key in (
            "candidate_total", "reviewed", "pending", "correct", "adjusted", "rejected",
            "irrelevant", "irrelevant_correct", "irrelevant_adjusted", "added", "reconstructed", "manual_added", "detected_desired", "desired_total",
        )
    }
    totals.update({
        "direct_coverage": _ratio(totals["detected_desired"], totals["desired_total"]),
        "structural_coverage": _ratio(totals["detected_desired"] + totals["reconstructed"], totals["desired_total"]),
        "reconstruction_rate": _ratio(totals["reconstructed"], totals["desired_total"]),
        "exact_box_rate": _ratio(max(0, totals["correct"] - totals["irrelevant_correct"]), totals["desired_total"]),
        "adjustment_rate": _ratio(max(0, totals["adjusted"] - totals["irrelevant_adjusted"]), totals["detected_desired"]),
        "false_candidate_rate": _ratio(totals["rejected"], totals["candidate_total"]),
        "fallback_need": _ratio(totals["manual_added"], totals["desired_total"]),
    })

    reviewed_sources = sum(1 for item in sources if item["review_completed"])
    incomplete_sources = max(0, len(sources) - reviewed_sources)
    sources_with_tables = sum(1 for item in sources if item["candidate_total"] > 0)

    ready = False
    state = "not_started"
    title = "Voer eerst de tabelanalyse uit"
    summary = "Er zijn nog geen PP-Structure tabelcellen om te beoordelen."
    next_step = "Voer Stap 2 · Tabelstructuur detecteren uit."
    tone = "warning"

    if sources:
        if totals["candidate_total"] == 0:
            state = "no_cells"
            title = "Geen bruikbare tabelcellen gevonden"
            summary = "PP-Structure heeft in de huidige bronnen geen reviewbare tabelcellen opgeleverd."
            next_step = "Controleer de ruwe table-regions in Stap 3; als dit structureel is, moet het table-model worden aangepast of getraind."
        elif totals["pending"] > 0 or incomplete_sources > 0:
            state = "needs_review"
            title = "Tabelreview nog niet afgerond"
            parts = []
            if totals["pending"] > 0:
                parts.append(f"{totals['pending']} tabelcel-kandidaten zijn nog niet beoordeeld")
            if incomplete_sources > 0:
                parts.append(f"{incomplete_sources} bronafbeelding(en) zijn nog niet expliciet als klaar gemarkeerd")
            summary = "; ".join(parts) + ". Coverage is pas betrouwbaar nadat je per bron ook naar ontbrekende cellen hebt gekeken."
            next_step = "Open Stap 3 · Tabelcellen reviewen, teken ontbrekende functionele cellen en kies daarna Afbeelding klaar."
        elif totals["desired_total"] == 0:
            state = "no_ground_truth"
            title = "Nog geen bruikbare doelcellen bevestigd"
            summary = "De review is afgerond, maar er zijn nog geen positieve doelcellen om table coverage tegen af te zetten."
            next_step = "Controleer in Stap 3 welke tabelcellen functioneel relevant zijn en voeg ontbrekende cellen toe."
        else:
            coverage = float(totals["structural_coverage"])
            direct_coverage = float(totals["direct_coverage"])
            false_rate = float(totals["false_candidate_rate"])
            adjustment_rate = float(totals["adjustment_rate"])
            if (
                coverage >= minimum_direct_coverage
                and false_rate <= maximum_false_candidate_rate
                and adjustment_rate <= maximum_adjustment_rate
            ):
                ready = True
                state = "table_only_sufficient"
                tone = "success"
                title = "Table-first is sterk genoeg als primaire geometriebron"
                summary = (
                    f"PP-Structure levert {direct_coverage:.1%} direct en de structurele reconstructie brengt de functionele coverage op {coverage:.1%}; "
                    f"{totals['manual_added']} cellen ({totals['fallback_need']:.1%}) moesten nog echt handmatig worden aangevuld."
                )
                next_step = "Ga door naar Mapping Studio. Houd de losse box-detector alleen als latere fallback voor uitzonderingen."
            elif coverage >= 0.80:
                state = "fallback_needed"
                tone = "info"
                title = "Table-first is bruikbaar, maar nog niet zelfstandig voldoende"
                summary = (
                    f"PP-Structure dekt {coverage:.1%} van de gewenste cellen. "
                    f"{totals['reconstructed']} cellen zijn geometrisch gereconstrueerd en {totals['manual_added']} cellen ({totals['fallback_need']:.1%}) vragen nog echte fallback; "
                    f"{false_rate:.1%} van de voorgestelde table-cellen is afgewezen."
                )
                if adjustment_rate > maximum_adjustment_rate:
                    next_step = "Primaire oorzaak: box-geometrie. Bekijk de aangepaste cellen en controleer of de volledige functionele cel consequent wordt gebruikt; dit wijst eerder op table-cell fine-tuning/normalisatie dan op PicoDet."
                elif false_rate > maximum_false_candidate_rate:
                    next_step = "Primaire oorzaak: te veel onbruikbare table-cellen. Bekijk de afgewezen kandidaten per bron om te bepalen welke table-regio/kolom Paddle verkeerd structureert."
                else:
                    next_step = "Primaire oorzaak: ontbrekende cellen. Bekijk de handmatig toegevoegde cellen; die vormen de concrete trainingsvoorbeelden voor een wireless table-cell fine-tune."
            else:
                state = "table_training_recommended"
                tone = "warning"
                title = "Standaard table-model mist te veel voor table-only gebruik"
                summary = (
                    f"PP-Structure dekt momenteel {coverage:.1%} van de gewenste cellen; "
                    f"{totals['fallback_need']:.1%} moest buiten de ruwe table-detectie worden toegevoegd."
                )
                next_step = "Gebruik de reviewcorrecties als table-cell trainingsdata en fine-tune eerst de wireless table-cell detector voordat de losse box-detector terugkomt."

    canonical_state: dict[str, Any] | None = None
    if load_table_cell_ground_truth(db.path.parent) is not None:
        canonical_state = ground_truth_review_state(db.path.parent)
        canonical_source_count = int(canonical_state.get("source_count") or 0)
        canonical_cell_count = int(canonical_state.get("gt_cell_count") or 0)
        canonical_open_count = int(canonical_state.get("open_source_count") or 0)
        ready = bool(
            canonical_source_count > 0
            and canonical_cell_count > 0
            and canonical_open_count == 0
        )
        if ready:
            state = "canonical_gt_ready"
            tone = "success"
            title = "Canonieke table-cell Ground Truth is klaar"
            summary = (
                f"{canonical_cell_count} canonieke GT-cellen over {canonical_source_count} bronafbeelding(en); "
                "0 GT-bronnen staan nog open. Detector-FP's en geometriescores zijn vanaf hier diagnostisch en blokkeren Mapping niet meer."
            )
            next_step = "Ga door naar Mapping Studio."
        elif canonical_source_count == 0 or canonical_cell_count == 0:
            state = "canonical_gt_empty"
            tone = "warning"
            title = "Canonieke Ground Truth ontbreekt"
            summary = "Er is wel een canoniek GT-bestand, maar het bevat nog geen bruikbare bronnen/cellen."
            next_step = "Ga terug naar Ground Truth beheren en maak/bevestig de canonieke table-cell GT."
        else:
            state = "canonical_gt_needs_review"
            tone = "warning"
            title = "Canonieke Ground Truth is nog niet volledig gecontroleerd"
            summary = (
                f"{canonical_open_count} van {canonical_source_count} GT-bronafbeelding(en) staan nog open."
            )
            next_step = "Open Ground Truth beheren en markeer de resterende bronafbeeldingen als gecontroleerd."

    return {
        "strategy": "table_first",
        "ready": ready,
        "state": state,
        "tone": tone,
        "title": title,
        "reason": summary,
        "summary": summary,
        "next_step": next_step,
        "gate_source": "canonical_gt" if canonical_state is not None else "legacy_table_review",
        "canonical_gt": ({
            "source_count": int(canonical_state.get("source_count") or 0),
            "gt_cell_count": int(canonical_state.get("gt_cell_count") or 0),
            "open_source_count": int(canonical_state.get("open_source_count") or 0),
            "completed_source_count": int(canonical_state.get("completed_source_count") or 0),
        } if canonical_state is not None else None),
        "sources": sources,
        "source_count": len(sources),
        "sources_with_tables": sources_with_tables,
        "reviewed_sources": reviewed_sources,
        "incomplete_sources": incomplete_sources,
        "totals": totals,
        "thresholds": {
            "minimum_direct_coverage": minimum_direct_coverage,
            "maximum_false_candidate_rate": maximum_false_candidate_rate,
            "maximum_adjustment_rate": maximum_adjustment_rate,
        },
    }
