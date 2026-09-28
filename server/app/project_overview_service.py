from datetime import date


def _parse_date(value):
    if isinstance(value, date):
        return value

    if isinstance(value, str):
        return date.fromisoformat(value)

    return None


def calculate_progress(milestones):
    total_hours = sum(
        milestone.get("estimatedHours", 0)
        for milestone in milestones
    )

    if total_hours == 0:
        return 0

    completed_hours = sum(
        milestone.get("estimatedHours", 0)
        for milestone in milestones
        if milestone.get("status") == "done"
    )

    return round(
        completed_hours / total_hours * 100
    )


def calculate_days_remaining(due_date):
    due_date = _parse_date(due_date)

    if due_date is None:
        return 0

    return (due_date - date.today()).days


def calculate_remaining_minutes(milestones):
    remaining_hours = sum(
        milestone.get("estimatedHours", 0)
        for milestone in milestones
        if milestone.get("status") != "done"
    )

    return round(remaining_hours * 60)


def calculate_overdue_count(milestones):
    today = date.today()

    count = 0

    for milestone in milestones:
        if milestone.get("status") == "done":
            continue

        due_date = _parse_date(
            milestone.get("dueDate")
        )

        if due_date is None:
            continue

        if due_date < today:
            count += 1

    return count


def calculate_risk(
    remaining_minutes,
    available_minutes,
    overdue_count,
):
    if overdue_count > 0:
        return "high"

    if available_minutes <= 0:
        return "high"

    ratio = remaining_minutes / available_minutes

    if ratio > 1:
        return "high"

    if ratio >= 0.8:
        return "medium"

    return "low"