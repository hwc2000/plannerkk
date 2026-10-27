"""Code-bounded, optional environment suggestions; never rewrite task scope or time."""
from copy import deepcopy
from collections import defaultdict
from math import floor


def suggest_environments(entries, insights):
    """Suggest places on at most 60% of new ordinary tasks in each project.

    Success ratio is evidence, NOT a required allocation. Unspecified tasks stay
    unspecified. Never invent an alternative or add travel/cost to a schedule.
    """
    result = deepcopy(entries)
    grouped = defaultdict(list)
    for index, entry in enumerate(result):
        if entry.get("kind") == "task" and not entry.get("completed") and not entry.get("starter"):
            grouped[entry.get("projectId")].append(index)
    for owner, indices in grouped.items():
        scoped = (insights.get("byProject") or {}).get(owner, {}) if "byProject" in insights else insights
        options = [item for item in scoped.get("recommendations", [])
                   if item.get("field") == "place" and isinstance(item.get("value"), str)
                   and item["value"].strip() and (item.get("evidence") or {}).get("status") == "supported"]
        if not options:
            continue
        limit = floor(len(indices) * .6)
        for offset in range(limit):
            # Spread hints rather than assigning every consecutive task a place.
            index = indices[floor(offset * len(indices) / limit)]
            choice = options[offset % len(options)]
            proof = choice["evidence"]
            result[index]["environmentSuggestion"] = {
                "place": choice["value"], "optional": True, "source": "project_check_ins",
                "knownFocusDays": proof.get("knownFocusDays", 0),
                "goodFocusDays": proof.get("goodFocus", 0),
                "goodFocusRatio": proof.get("goodFocusRatio"),
            }
    return result
