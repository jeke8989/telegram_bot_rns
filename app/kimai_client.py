"""
Async client for Kimai Time Tracking REST API.
"""

import logging
from typing import Any

import aiohttp

from app.retry import retry_async

logger = logging.getLogger(__name__)


class KimaiClient:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    @retry_async(attempts=3, base_delay=0.5)
    async def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.get(url, params=params, ssl=False) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Kimai API error %s %s: %s", resp.status, url, body)
                    raise RuntimeError(f"Kimai API {resp.status}: {body[:300]}")
                return await resp.json()

    async def get_teams(self) -> list[dict]:
        return await self._get("/api/teams")

    async def get_team(self, team_id: int) -> dict:
        return await self._get(f"/api/teams/{team_id}")

    async def get_users(self) -> list[dict]:
        return await self._get("/api/users", params={"size": "500"})

    async def get_user(self, user_id: int) -> dict:
        return await self._get(f"/api/users/{user_id}")

    async def get_users_with_rates(self) -> list[dict]:
        """Fetch all users and enrich each with hourly_rate and email from detail."""
        users = await self.get_users()
        import asyncio
        async def enrich(u: dict) -> dict:
            try:
                detail = await self.get_user(u["id"])
                u["email"] = detail.get("email") or u.get("email")
                prefs = {p["name"]: p["value"] for p in detail.get("preferences", [])}
                rate_raw = prefs.get("hourly_rate")
                try:
                    u["hourly_rate"] = float(rate_raw) if rate_raw not in (None, "", "0", 0) else None
                except (TypeError, ValueError):
                    u["hourly_rate"] = None
            except Exception as e:
                logger.warning("Failed to enrich Kimai user %s: %s", u.get("id"), e)
                u.setdefault("hourly_rate", None)
                u.setdefault("email", None)
            return u
        return list(await asyncio.gather(*[enrich(u) for u in users]))

    async def get_projects(self) -> list[dict]:
        return await self._get("/api/projects", params={"size": "500"})

    async def get_customers(self) -> list[dict]:
        return await self._get("/api/customers", params={"size": "500"})

    async def get_customer(self, customer_id: int) -> dict:
        return await self._get(f"/api/customers/{customer_id}")

    async def get_activities(self) -> list[dict]:
        return await self._get("/api/activities", params={"size": "500"})

    async def get_project_timesheets(
        self,
        project_id: int,
        begin: str,
        end: str,
    ) -> list[dict]:
        """Fetch all timesheets for a project (across all users) in the date range."""
        users = await self.get_users()
        all_records: list[dict] = []
        for user in users:
            uid = user.get("id")
            if not uid:
                continue
            page = 1
            while True:
                data = await self._get(
                    "/api/timesheets",
                    params={
                        "user": str(uid),
                        "project": str(project_id),
                        "begin": begin,
                        "end": end,
                        "size": "500",
                        "page": str(page),
                    },
                )
                all_records.extend(data)
                if len(data) < 500:
                    break
                page += 1
        return all_records

    async def build_client_report_data(
        self,
        project_ids: list[int],
        begin: str,
        end: str,
    ) -> dict:
        """Collect data for a client PDF report (no money, only hours).

        Returns dict with keys: projects, activities_map, users_map,
        report_by_project (project_id -> list of timesheet dicts with resolved names).
        """
        activities_list = await self.get_activities()
        activities_map: dict[int, str] = {a["id"]: a["name"] for a in activities_list}

        users_list = await self.get_users()
        users_map: dict[int, str] = {}
        for u in users_list:
            users_map[u["id"]] = u.get("alias") or u.get("username") or f"User {u['id']}"

        projects_list = await self.get_projects()
        projects_map: dict[int, str] = {p["id"]: p["name"] for p in projects_list}

        report_by_project: dict[int, list[dict]] = {}

        for pid in project_ids:
            timesheets = await self.get_project_timesheets(pid, begin, end)
            entries: list[dict] = []
            for ts in timesheets:
                entries.append({
                    "date": ts.get("begin", ""),
                    "activity": activities_map.get(ts.get("activity", 0), "Other"),
                    "user": users_map.get(ts.get("user", 0), "Unknown"),
                    "description": ts.get("description") or "",
                    "hours": (ts.get("duration", 0) or 0) / 3600,
                })
            entries.sort(key=lambda e: e["date"])
            report_by_project[pid] = entries

        return {
            "projects_map": projects_map,
            "activities_map": activities_map,
            "users_map": users_map,
            "report_by_project": report_by_project,
        }

    async def get_timesheets(
        self,
        user_id: int,
        begin: str,
        end: str,
    ) -> list[dict]:
        """Fetch timesheets for a user in the given date range.

        Args:
            user_id: Kimai user ID
            begin: Start date in format YYYY-MM-DDTHH:mm:ss
            end: End date in format YYYY-MM-DDTHH:mm:ss
        """
        all_records: list[dict] = []
        page = 1
        while True:
            data = await self._get(
                "/api/timesheets",
                params={
                    "user": str(user_id),
                    "begin": begin,
                    "end": end,
                    "size": "500",
                    "page": str(page),
                },
            )
            all_records.extend(data)
            if len(data) < 500:
                break
            page += 1
        return all_records

    async def build_team_report_data(
        self,
        begin: str,
        end: str,
    ) -> dict:
        """Collect all data needed for team reports.

        Returns dict with keys: teams, projects_map, report_by_team.
        report_by_team maps team_id -> list of member dicts with timesheets.
        """
        teams_list = await self.get_teams()
        projects_list = await self.get_projects()
        projects_map: dict[int, str] = {p["id"]: p["name"] for p in projects_list}

        teams: list[dict] = []
        report_by_team: dict[int, list[dict]] = {}

        # Fetch activities once to detect "Бонусы" activity type
        activities_list = await self.get_activities()
        bonus_activity_ids: set[int] = {
            a["id"] for a in activities_list
            if "бонус" in (a.get("name") or "").lower()
        }

        for team_summary in teams_list:
            team_id = team_summary["id"]
            team_detail = await self.get_team(team_id)
            teams.append(team_detail)

            members = team_detail.get("members", [])
            member_reports: list[dict] = []

            for member in members:
                user_info = member.get("user", {})
                user_id = user_info.get("id")
                if not user_id:
                    continue

                alias = (
                    user_info.get("alias")
                    or user_info.get("username")
                    or f"User {user_id}"
                )
                is_teamlead = member.get("teamlead", False)

                timesheets = await self.get_timesheets(user_id, begin, end)

                project_hours: dict[int, float] = {}
                project_money: dict[int, float] = {}
                bonus_from_activity: float = 0.0

                for ts in timesheets:
                    proj_id = ts.get("project")
                    activity_id = ts.get("activity")
                    duration_sec = ts.get("duration", 0) or 0
                    rate = ts.get("rate", 0) or 0

                    # Timesheets with "Бонусы" activity go to bonus, not regular earnings
                    if activity_id in bonus_activity_ids:
                        bonus_from_activity += rate
                    elif proj_id is not None:
                        project_hours[proj_id] = project_hours.get(proj_id, 0) + duration_sec / 3600
                        project_money[proj_id] = project_money.get(proj_id, 0) + rate

                member_reports.append({
                    "user_id": user_id,
                    "name": alias,
                    "is_teamlead": is_teamlead,
                    "account_number": user_info.get("accountNumber") or "",
                    "project_hours": project_hours,
                    "project_money": project_money,
                    "total_hours": sum(project_hours.values()),
                    "total_money": sum(project_money.values()),
                    "bonus_from_activity": bonus_from_activity,
                })

            report_by_team[team_id] = member_reports

        return {
            "teams": teams,
            "projects_map": projects_map,
            "report_by_team": report_by_team,
        }
