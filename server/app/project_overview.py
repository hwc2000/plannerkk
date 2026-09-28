from datetime import date, timedelta

from fastapi import APIRouter

from server.app.project_overview_service import (
    calculate_progress,
    calculate_days_remaining,
    calculate_remaining_minutes,
    calculate_overdue_count,
    calculate_risk,
)


router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
)


@router.get("/{project_id}/overview")
def get_project_overview(project_id: str):
    # TODO:
    # Supabase 연결 이후 실제 project / milestone 조회로 교체

    project = {
        "id": project_id,
        "title": "PlannerKK 캡스톤 프로젝트",
        "goal": "AI 기반 일정 관리 서비스 구현",
        "startDate": date.today().isoformat(),
        "dueDate": (
            date.today() + timedelta(days=12)
        ).isoformat(),
        "priority": "high",
        "status": "in_progress",
    }

    milestones = [
        {
            "id": "m1",
            "projectId": project_id,
            "title": "기획 완료",
            "startDate": (
                date.today() - timedelta(days=20)
            ).isoformat(),
            "dueDate": (
                date.today() - timedelta(days=15)
            ).isoformat(),
            "estimatedHours": 5,
            "status": "done",
        },
        {
            "id": "m2",
            "projectId": project_id,
            "title": "프론트엔드 구현",
            "startDate": (
                date.today() - timedelta(days=10)
            ).isoformat(),
            "dueDate": (
                date.today() - timedelta(days=2)
            ).isoformat(),
            "estimatedHours": 10,
            "status": "done",
        },
        {
            "id": "m3",
            "projectId": project_id,
            "title": "백엔드 구현",
            "startDate": date.today().isoformat(),
            "dueDate": (
                date.today() + timedelta(days=5)
            ).isoformat(),
            "estimatedHours": 15,
            "status": "in_progress",
        },
        {
            "id": "m4",
            "projectId": project_id,
            "title": "최종 테스트",
            "startDate": (
                date.today() - timedelta(days=3)
            ).isoformat(),
            "dueDate": (
                date.today() - timedelta(days=1)
            ).isoformat(),
            "estimatedHours": 5,
            "status": "todo",
        },
    ]

    # TODO:
    # user_profiles + calendar_events 연결 후
    # 실제 가용 시간 계산
    available_minutes = 720

    progress = calculate_progress(
        milestones
    )

    days_remaining = calculate_days_remaining(
        project["dueDate"]
    )

    remaining_minutes = (
        calculate_remaining_minutes(
            milestones
        )
    )

    overdue_count = calculate_overdue_count(
        milestones
    )

    risk = calculate_risk(
        remaining_minutes,
        available_minutes,
        overdue_count,
    )

    return {
        "projectId": project_id,
        "progressPercent": progress,
        "daysRemaining": days_remaining,
        "overdueMilestoneCount": overdue_count,
        "remainingEstimatedMinutes":
            remaining_minutes,
        "availableMinutesUntilDeadline":
            available_minutes,
        "riskLevel": risk,
    }