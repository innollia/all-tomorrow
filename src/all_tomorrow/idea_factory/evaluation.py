"""Staff evaluation from user judgments, and promotion/retirement.

The ground truth is the user's: proposal approve/reject and kill reviews. A staff
member is scored as a (role, model group) combination, so only samples after its
last change (hire, promotion) count.

Known bias: ideas rejected inside the council never reach the user, so council
members are only scored on ideas they collectively passed.
"""
from __future__ import annotations

from typing import Any

from all_tomorrow.idea_factory.config import Roster
from all_tomorrow.idea_factory.store import Store

COUNCIL_ROLES = ("visionary", "operator", "advocate", "skeptic")


def _samples(store: Store, roster: Roster, member: dict[str, Any]) -> list[bool]:
    since = member["changed_at"]
    decided = [p for p in store.proposals() if p["status"] in ("APPROVED", "REJECTED") and p["decided_at"] > since]
    if member["role"] == "ideator":
        ideas = {i["id"]: i for i in store.ideas(limit=100000)}
        return [p["status"] == "APPROVED" for p in decided if ideas.get(p["idea_id"], {}).get("ideator_id") == member["id"]]
    if member["role"] == "synthesizer":
        return [i["review"] == "correct" for i in store.ideas(status="KILLED", limit=100000)
                if i["synth_id"] == member["id"] and i["review"] and i["reviewed_at"] > since]
    if member["role"] in COUNCIL_ROLES:
        results = []
        for proposal in decided:
            final = [v for v in store.votes(proposal["idea_id"])
                     if v["staff_id"] == member["id"] and v["round"] == roster.council_rounds]
            for vote in final:
                if vote["stance"] == "support":
                    results.append(proposal["status"] == "APPROVED")
                elif vote["stance"] == "oppose":
                    results.append(proposal["status"] == "REJECTED")
        return results
    return []


def evaluate(store: Store, roster: Roster) -> list[dict[str, Any]]:
    report = []
    for member in store.staff(include_retired=False):
        samples = _samples(store, roster, member)
        score = sum(samples) / len(samples) if samples else None
        if len(samples) < roster.evaluation_min_samples:
            verdict = "EVALUATING"
        elif score > roster.promote_above:
            verdict = "PROMOTE"
        elif score < roster.retire_below:
            verdict = "RETIRE"
        else:
            verdict = "KEEP"
        report.append({**member, "samples": len(samples), "score": score, "verdict": verdict})
    return report


def _next_tier(roster: Roster, current: str) -> str | None:
    if current not in roster.tiers:
        return roster.tiers[0]
    index = roster.tiers.index(current)
    return roster.tiers[index + 1] if index + 1 < len(roster.tiers) else None


def apply_policy(store: Store, roster: Roster, actor: str = "policy") -> list[dict[str, Any]]:
    actions = []
    for row in evaluate(store, roster):
        detail = {"staff_id": row["id"], "samples": row["samples"], "score": row["score"], "from": row["model_group"]}
        if row["verdict"] == "PROMOTE":
            target = _next_tier(roster, row["model_group"])
            if target is None:
                continue
            store.set_staff_group(row["id"], target)
            # Promotion also widens profile access: one more level on top of the role's base.
            base = next((m for m in roster.staff if m["role"] == row["role"]), {})
            new_level = store.set_access(row["id"], base.get("access_level", 0), base.get("access_scopes", []),
                                         bonus=row.get("promotion_bonus", 0) + 1)
            store.audit(actor, "staff_promote", {**detail, "to": target, "access_level": new_level})
            store.event("staff", f"{row['name']} 승진: {row['model_group']} → {target} (점수 {row['score']:.2f}, 표본 {row['samples']})",
                        staff_id=row["id"])
            actions.append({"action": "promote", **detail, "to": target})
        elif row["verdict"] == "RETIRE":
            target = _next_tier(roster, row["model_group"]) or roster.tiers[0]
            if target == row["model_group"]:
                target = roster.tiers[0]
            store.retire(row["id"])
            base = next((m for m in roster.staff if m["role"] == row["role"]), {})
            new_id = store.hire(row["role"], row["name"], target, generation=row["generation"] + 1,
                                access_level=base.get("access_level", 0), access_scopes=base.get("access_scopes", []))
            store.audit(actor, "staff_retire", {**detail, "replacement": new_id, "to": target})
            store.event("staff", f"{row['name']} {row['generation']}세대 퇴출 (점수 {row['score']:.2f}, 표본 {row['samples']}) → "
                        f"{row['generation'] + 1}세대 채용 ({target})", staff_id=new_id)
            actions.append({"action": "retire", **detail, "replacement": new_id, "to": target})
    return actions
