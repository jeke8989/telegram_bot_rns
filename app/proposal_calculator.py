"""
AI-powered project estimation engine for commercial proposals.
Uses Claude Sonnet 4.5 via OpenRouter to analyze project descriptions
and produce structured hour/cost breakdowns by department.
"""

import aiohttp
import json
import logging
import re

logger = logging.getLogger(__name__)

ESTIMATION_NORMS = """
## Reference Estimation Norms (role distribution as % of total development hours)

These are typical hour distributions for web/mobile projects. Use them as guardrails:
- Project Management (PM): 10-15% of total hours
- UX/UI Design: 12-18% of total hours
- Frontend Development: 25-30% of total hours
- Backend Development: 28-35% of total hours
- QA / Testing: 8-12% of total hours

## Reference Complexity Benchmarks (per-feature hour ranges)

Simple CRUD page (list + card + create/edit): 20-40 hours total
Medium complexity module (dashboard, analytics, charts): 60-120 hours total
Complex module (real-time chat, billing, document flow): 100-200 hours total
Authentication & registration: 20-40 hours total
Landing page: 40-80 hours total
Admin panel with roles: 80-200 hours total
Mobile app (single role, 5-8 screens): 150-300 hours total
Integration with external API: 15-40 hours per integration
Preparation phase (architecture, DB design, tech docs): 80-190 hours

## MVP vs Full estimation
- MVP: Focus on core features only. Reduce scope by ~40-50%. Prioritize must-have functionality.
  Team: 2-3 people. Timeline: 1-2 weeks. Keep it tight and focused.
- Full: Complete feature set with all described functionality.
  Team: 3-5 people. Timeline depends on scope but typically 1-4 months.

## Timeline Calculation Rules
- Calculate timeline_weeks (not months!) based on total hours divided by team capacity.
- MVP team: 2-3 people working ~40 hours/week each. So capacity = 80-120 hours/week.
  A 100-hour MVP project = ~1 week. A 200-hour project = ~2 weeks. Max 2-3 weeks for MVP.
- Full project team: 3-5 people working ~40 hours/week each. Capacity = 120-200 hours/week.
  Timeline typically 4-16 weeks depending on total hours.
- Return timeline_weeks in the JSON (min/max in weeks).

## Design options
- Full Design: Include full UX/UI design hours (wireframes + mockups + design system)
- Wireframes Only: ~40% of full design hours (structure and layout only, no visual polish)
- No Design: Zero design hours (development uses basic UI framework)
"""


class ProposalCalculator:
    def __init__(self, openrouter_api_key: str):
        self.api_key = openrouter_api_key
        self.model = "anthropic/claude-sonnet-4.5"
        self.base_url = "https://openrouter.ai/api/v1"

    async def calculate_proposal(
        self,
        project_description: str,
        proposal_type: str,
        budget_constraint: float | None,
        budget_currency: str | None,
        design_type: str,
        hourly_rate: float,
        currency: str,
    ) -> dict:
        """
        Analyze a project description and return a structured estimation.

        Args:
            project_description: Full text of the project description / TZ
            proposal_type: "mvp" or "full"
            budget_constraint: Maximum budget amount or None
            budget_currency: Currency of budget constraint
            design_type: "full_design", "wireframes", or "no_design"
            hourly_rate: Cost per hour
            currency: "$" or "₽"

        Returns:
            Structured dict with modules, hours, costs, and timeline.
        """
        prompt = self._build_prompt(
            project_description,
            proposal_type,
            budget_constraint,
            budget_currency,
            design_type,
            hourly_rate,
            currency,
        )

        result = await self._call_api(prompt)
        if result is None:
            return self._error_result("AI API call failed")

        parsed = self._parse_response(result)
        if parsed is None:
            return self._error_result("Failed to parse AI response")

        ai_keys = list(parsed.keys())
        has_persp_before = "perspectives" in parsed
        has_stages_before = "stages" in parsed
        persp_count_before = len(parsed.get("perspectives", []))
        stages_count_before = len(parsed.get("stages", []))
        logger.info(
            "AI response parsed: keys=%s, perspectives=%s(%d), stages=%s(%d)",
            ai_keys, has_persp_before, persp_count_before, has_stages_before, stages_count_before,
        )

        parsed = self._apply_multipliers(parsed, design_type, hourly_rate, budget_constraint)

        logger.info(
            "After _apply_multipliers: perspectives=%d, stages=%d",
            len(parsed.get("perspectives", [])), len(parsed.get("stages", [])),
        )

        if "perspectives" not in parsed or not parsed["perspectives"]:
            logger.warning("FINAL CHECK: perspectives still missing after _apply_multipliers, forcing generation")
            modules = parsed.get("modules", [])
            module_names = [m.get("name", "") for m in modules if m.get("name")]
            parsed["perspectives"] = [
                {"title": "Аналитика и отчёты", "description": "Наглядные графики и отчёты — вы видите, что работает, и принимаете решения на основе данных"},
                {"title": "Автоматические уведомления", "description": "Клиенты получают напоминания, а вы — оповещения о важных событиях. Ничего не теряется."},
                {"title": "Мобильное приложение", "description": "Удобное приложение для телефона — ваши клиенты всегда на связи, даже в дороге"},
                {"title": "Умные рекомендации", "description": "Система подсказывает клиентам подходящие товары или услуги — средний чек растёт"},
                {"title": "Рост без ограничений", "description": "Система готова к увеличению нагрузки — когда бизнес вырастет, продукт справится"},
            ]

        if "stages" not in parsed or not parsed["stages"]:
            logger.warning("FINAL CHECK: stages still missing after _apply_multipliers, forcing generation")
            totals_data = parsed.get("totals", {})
            total_avg = (totals_data.get("total_hours", {}).get("min", 40) + totals_data.get("total_hours", {}).get("max", 60)) / 2

            forced_stages = []
            design_hours_total = (totals_data.get("design", {}).get("min", 0) + totals_data.get("design", {}).get("max", 0)) // 2
            if design_type != "no_design" and design_hours_total > 0:
                dh = max(3, design_hours_total)
                forced_stages.append({
                    "name": "UX/UI Дизайн",
                    "tasks": [
                        {"name": "Проектирование структуры экранов и навигации", "hours": max(1, dh // 3)},
                        {"name": "Создание вайрфреймов ключевых страниц", "hours": max(1, dh // 3)},
                        {"name": "Согласование и финализация макетов", "hours": max(1, dh - 2 * (dh // 3))},
                    ]
                })

            dev_hours = int(total_avg * 0.7)
            modules = parsed.get("modules", [])
            dev_tasks = []
            for mod in modules:
                mod_name = mod.get("name", "Модуль")
                mod_hours = (mod.get("total", {}).get("min", 4) + mod.get("total", {}).get("max", 8)) // 2
                for si in mod.get("sub_items", []):
                    if isinstance(si, dict):
                        si_hours = (si.get("hours", {}).get("min", 2) + si.get("hours", {}).get("max", 4)) // 2
                        dev_tasks.append({"name": si.get("name", "Задача"), "hours": max(1, si_hours), "module": mod_name})
                if not mod.get("sub_items"):
                    dev_tasks.append({"name": f"Разработка модуля {mod_name}", "hours": max(2, mod_hours), "module": mod_name})
            forced_stages.append({"name": "Разработка приложения", "tasks": dev_tasks or [{"name": "Основная разработка", "hours": dev_hours}]})

            qa_hours = max(4, int(total_avg * 0.12))
            forced_stages.append({
                "name": "Тестирование и запуск",
                "tasks": [
                    {"name": "Проверка всех функций", "hours": max(1, qa_hours // 3)},
                    {"name": "Исправление ошибок", "hours": max(1, qa_hours // 3)},
                    {"name": "Запуск на рабочем сервере", "hours": max(1, qa_hours - 2 * (qa_hours // 3))},
                ]
            })
            parsed["stages"] = forced_stages

        parsed["hourly_rate"] = hourly_rate
        parsed["currency"] = currency
        parsed["proposal_type"] = proposal_type
        parsed["design_type"] = design_type

        return parsed

    def _build_prompt(
        self,
        project_description: str,
        proposal_type: str,
        budget_constraint: float | None,
        budget_currency: str | None,
        design_type: str,
        hourly_rate: float,
        currency: str,
    ) -> str:
        budget_section = ""
        if budget_constraint is not None:
            target_hours = budget_constraint / hourly_rate
            budget_section = f"""
## STRICT Budget Constraint
The client's budget is **EXACTLY {budget_constraint:,.0f} {budget_currency or currency}**.
Hourly rate is {hourly_rate} {currency}/hour, so the target total hours MUST be **{target_hours:,.0f}**.

CRITICAL: The final total_cost AVERAGE ((min+max)/2) MUST equal EXACTLY {budget_constraint:,.0f}.
Set total_hours so that (min+max)/2 * {hourly_rate} = {budget_constraint:,.0f}.
Adjust scope, trim non-essential features, or redistribute hours to hit this target precisely.
Do NOT exceed the budget. Do NOT undershoot the budget.
"""

        design_label = {
            "full_design": "Full UX/UI Design (wireframes + mockups + design system)",
            "wireframes": "Wireframes Only (structure and layout, no visual polish)",
            "no_design": "No Design (zero design hours, basic UI framework)",
        }.get(design_type, design_type)

        no_design_instruction = ""
        if design_type == "no_design":
            no_design_instruction = """
## CRITICAL: No Design
The client chose NO DESIGN. All design hours MUST be exactly 0 for every module, preparation phase, and totals.
Do NOT include any design work at all — not even wireframes, mockups, or design system work.
"""

        if design_type == "no_design":
            design_stage_instruction = '1. "UX/UI Дизайн" — NOT needed (design_type is no_design). Do NOT include this stage.'
        elif design_type == "wireframes":
            design_stage_instruction = '1. "UX/UI Дизайн" — MANDATORY. Include wireframe tasks (структура экранов, прототипирование, UX-сценарии). This stage MUST be present.'
        else:
            design_stage_instruction = '1. "UX/UI Дизайн" — MANDATORY. Include full design tasks (wireframes, mockups, design system, UI kit). This stage MUST be present.'

        return f"""You are an expert software project estimator for a web/mobile development agency.
Your task: analyze the project description below and produce a **detailed, structured estimation**
broken down into modules and roles.

{ESTIMATION_NORMS}

## Our Tech Stack (ALWAYS use these tools in estimates)
Our agency builds ALL projects using this exact stack. Factor these tools into every estimation:

**Frontend:** Next.js, React, TypeScript, Redux Toolkit, Tailwind CSS
**Backend:** NestJS, TypeORM, PostgreSQL, Redis, Socket.io
**Infrastructure:** Docker, CI/CD pipelines, Cloud deployments (VPS/AWS)

Because we have deep expertise and reusable boilerplates in this stack:
- We have ready-made project templates, auth modules, admin panels, and API scaffolding
- We reuse our component library and design system across projects
- Our team is highly specialized in this stack — no learning curve

## AI-Assisted Development
Our team uses AI-assisted development tools (Cursor AI, GitHub Copilot), which significantly speeds up work:
- **Frontend development takes 40% less time** than traditional estimates (apply 0.6x multiplier)
- **Backend development takes 30% less time** than traditional estimates (apply 0.7x multiplier)
- AI generates boilerplate code, tests, documentation, and handles routine refactoring
- PM and QA are NOT affected by AI speedups
- Combined with our stack expertise, this results in ~30% total budget savings and ~3x faster delivery vs traditional agencies
Factor these speedups into ALL your hour estimates from the start.

## Input Parameters
- Proposal type: **{proposal_type.upper()}**
- Design approach: **{design_label}**
- Hourly rate: **{hourly_rate} {currency}/hour**
{budget_section}
{no_design_instruction}

## Project Description / Technical Specification
---
{project_description}
---

## Your Task

1. Break the project into logical modules/sections.
   IMPORTANT: Name modules in SIMPLE BUSINESS LANGUAGE that a non-technical entrepreneur understands.
   Good: "Личный кабинет пользователя", "Каталог товаров", "Система оплаты", "Уведомления"
   Bad: "API Gateway", "Auth Module", "WebSocket Service", "ORM Layer"
   Sub-task names should also be business-readable, not code-level.
   Good: "Форма входа и регистрация", "Страница товара с фото и описанием"
   Bad: "JWT middleware setup", "Redux store configuration"
2. For each module, estimate hours by role: PM, Design, Frontend, Backend, QA.
   Provide min-max ranges for each.
3. For each module, list 3-6 specific sub-tasks. Each sub-task MUST have its own total hour estimate (min-max).
   The sum of sub-task hours should approximately equal the module total.
4. Include a "Preparation Phase" module (architecture, DB design, tech docs, meetings) with sub-tasks.
5. Calculate totals.
6. Estimate project timeline in WEEKS (min-max). For MVP: 1-2 weeks with 2-3 people. For Full: calculate based on total hours / team capacity (3-5 people * 40h/week).
7. Estimate team_size (min-max number of people on the project).
8. Generate a short project name (2-5 words) if not obvious from the description.
9. project_description_short: Write 1-2 sentences in SIMPLE Russian that explain what the project does for the CLIENT'S BUSINESS. No technical terms. Example: "Платформа для онлайн-продажи курсов с личным кабинетом для учеников и преподавателей".

## CRITICAL: Output Format

Return ONLY valid JSON (no markdown, no ```json blocks, no comments). Use this exact structure:

{{
    "project_name": "Short project name in Russian",
    "project_description_short": "1-2 sentence description of the project in Russian",
    "modules": [
        {{
            "name": "Module name in Russian",
            "description": "Short description in Russian",
            "sub_items": [
                {{"name": "Task name in Russian", "hours": {{"min": 0, "max": 0}}}},
                {{"name": "Task name in Russian", "hours": {{"min": 0, "max": 0}}}}
            ],
            "hours": {{
                "pm": {{"min": 0, "max": 0}},
                "design": {{"min": 0, "max": 0}},
                "frontend": {{"min": 0, "max": 0}},
                "backend": {{"min": 0, "max": 0}},
                "qa": {{"min": 0, "max": 0}}
            }},
            "total": {{"min": 0, "max": 0}}
        }}
    ],
    "preparation_phase": {{
        "sub_items": [
            {{"name": "Task name in Russian", "hours": {{"min": 0, "max": 0}}}}
        ],
        "hours": {{
            "pm": {{"min": 0, "max": 0}},
            "design": {{"min": 0, "max": 0}},
            "frontend": {{"min": 0, "max": 0}},
            "backend": {{"min": 0, "max": 0}},
            "qa": {{"min": 0, "max": 0}}
        }},
        "total": {{"min": 0, "max": 0}}
    }},
    "totals": {{
        "pm": {{"min": 0, "max": 0}},
        "design": {{"min": 0, "max": 0}},
        "frontend": {{"min": 0, "max": 0}},
        "backend": {{"min": 0, "max": 0}},
        "qa": {{"min": 0, "max": 0}},
        "total_hours": {{"min": 0, "max": 0}},
        "total_cost": {{"min": 0.0, "max": 0.0}}
    }},
    "timeline_weeks": {{"min": 0, "max": 0}},
    "team_size": {{"min": 0, "max": 0}},
    "notes": ["Optional note 1", "Optional note 2"],
    "perspectives": [
        {{"title": "Short catchy title in Russian (3-5 words)", "description": "Compelling description in Russian (1-2 sentences) explaining the business value"}},
        {{"title": "Short catchy title in Russian (3-5 words)", "description": "Compelling description in Russian (1-2 sentences) explaining the business value"}}
    ],
    "stages": [
        {{
            "name": "UX/UI Дизайн",
            "tasks": [
                {{"name": "Task description in Russian", "hours": 16}}
            ]
        }},
        {{
            "name": "Разработка приложения",
            "tasks": [
                {{"name": "Task description in Russian", "hours": 20, "module": "Module name in Russian"}},
                {{"name": "Task description in Russian", "hours": 12, "module": "Module name in Russian"}}
            ]
        }},
        {{
            "name": "Тестирование и запуск",
            "tasks": [
                {{"name": "Task description in Russian", "hours": 8, "module": "Module name in Russian"}},
                {{"name": "Task description in Russian", "hours": 4}}
            ]
        }}
    ]
}}

Make sure total_cost = total_hours * {hourly_rate}.
All text content (names, descriptions, notes, sub_items, perspectives) MUST be in Russian.
Each sub_item MUST be an object with "name" (string) and "hours" ({{"min": N, "max": N}}).
timeline_weeks: for MVP typically 1-2 weeks, for Full projects calculate realistically.
team_size: for MVP 2-3, for Full 3-5.
## CRITICAL: perspectives (MANDATORY — DO NOT OMIT)
The "perspectives" array is REQUIRED and MUST contain 4-6 items. This is the "Version 2.0" roadmap — a logical continuation of THIS specific project.
Each perspective MUST be an object with "title" (catchy 3-5 word name in Russian) and "description" (1-2 sentences in Russian explaining the concrete business value).
IMPORTANT: Write perspectives in SIMPLE BUSINESS LANGUAGE that a non-technical entrepreneur can understand.
Do NOT use technical jargon (no "API", "микросервисы", "кеширование", "CDN").
Instead use language like: "больше клиентов", "автоматизация рутины", "рост продаж", "экономия времени".
Generate ideas that DIRECTLY extend the current project scope:
- Be a natural next step that builds on what was just developed (not generic features)
- Reference specific modules/features from the current project and show how they can evolve
- Example: if the project has a catalog → "Умные рекомендации товаров — покупатели находят нужное быстрее, средний чек растёт"
- Example: if the project has auth → "Личный кабинет для клиентов — история заказов, бонусы, персональные предложения"
Make the client excited to start Version 2.0 immediately after launch.
OUTPUT WILL BE REJECTED IF "perspectives" IS MISSING OR EMPTY.

## CRITICAL: stages rules (MUST FOLLOW — OUTPUT WILL BE REJECTED IF STAGES ARE MISSING)
The "stages" array MUST contain EXACTLY these phases:
{design_stage_instruction}
2. "Разработка приложения" — MANDATORY. All frontend and backend development, grouped by module. This stage MUST be present.
   Task names in this stage should be BUSINESS-READABLE. Good: "Страница каталога с фильтрами". Bad: "Redux store + API endpoints".
3. "Тестирование и запуск" — MANDATORY. QA, testing, bug fixing, deployment. This stage MUST ALWAYS be present — NO PROJECT ships without testing.

DO NOT skip any mandatory stage. DO NOT merge stages. Each stage is a SEPARATE entry in the "stages" array.
Do NOT include a "Скоупинг" stage. Scoping/planning hours are already covered by preparation_phase.

Each task in stages has a SINGLE "hours" integer (not min/max).
The SUM of all task hours across ALL stages MUST approximately equal the AVERAGE of totals.total_hours.min and totals.total_hours.max.
No double-counting between stages — each hour of work appears in exactly one stage.

## CRITICAL: module grouping inside stages
Tasks in "Разработка приложения" and "Тестирование и запуск" MUST have a "module" field matching one of the modules from the "modules" array.
This groups tasks visually by module. Example:
  {{"name": "Форма входа и регистрации", "hours": 8, "module": "Авторизация"}},
  {{"name": "API авторизации и JWT", "hours": 10, "module": "Авторизация"}},
  {{"name": "Список товаров с пагинацией", "hours": 12, "module": "Каталог товаров"}}
Tasks in "UX/UI Дизайн" do NOT need "module" — it is a flat list.
Each module should have 2-5 tasks. The "Разработка" stage should have the most tasks total (10-20).

Ensure all numbers are realistic and consistent. Double-check your math.
"""

    @staticmethod
    def _apply_multipliers(data: dict, design_type: str, hourly_rate: float, budget_constraint: float | None = None) -> dict:
        """Post-process AI estimation: enforce AI speedups and no-design constraint."""
        FRONTEND_MULT = 0.6
        BACKEND_MULT = 0.7

        def adjust_hours(hours: dict) -> dict:
            for key in ("min", "max"):
                hours["frontend"][key] = round(hours["frontend"][key] * FRONTEND_MULT)
                hours["backend"][key] = round(hours["backend"][key] * BACKEND_MULT)
                if design_type == "no_design":
                    hours["design"][key] = 0
            return hours

        def recalc_total(hours: dict) -> dict:
            roles = ("pm", "design", "frontend", "backend", "qa")
            return {
                "min": sum(hours[r]["min"] for r in roles),
                "max": sum(hours[r]["max"] for r in roles),
            }

        def scale_sub_items(module: dict, old_total: dict):
            """Scale sub_item hours proportionally after module total was adjusted."""
            sub_items = module.get("sub_items", [])
            new_total = module.get("total", {})
            for bound in ("min", "max"):
                old_val = old_total.get(bound, 0)
                new_val = new_total.get(bound, 0)
                if old_val > 0:
                    ratio = new_val / old_val
                    for si in sub_items:
                        if isinstance(si, dict) and "hours" in si:
                            si["hours"][bound] = max(1, round(si["hours"][bound] * ratio))

        for module in data.get("modules", []):
            if "hours" in module:
                old_total = dict(module.get("total", {}))
                module["hours"] = adjust_hours(module["hours"])
                module["total"] = recalc_total(module["hours"])
                scale_sub_items(module, old_total)

        if "preparation_phase" in data and "hours" in data["preparation_phase"]:
            old_total = dict(data["preparation_phase"].get("total", {}))
            data["preparation_phase"]["hours"] = adjust_hours(data["preparation_phase"]["hours"])
            data["preparation_phase"]["total"] = recalc_total(data["preparation_phase"]["hours"])
            scale_sub_items(data["preparation_phase"], old_total)

        if "totals" in data:
            totals = data["totals"]
            roles = ("pm", "design", "frontend", "backend", "qa")
            for role in roles:
                if role in totals:
                    totals[role]["min"] = sum(
                        m["hours"][role]["min"] for m in data.get("modules", []) if "hours" in m
                    ) + (data.get("preparation_phase", {}).get("hours", {}).get(role, {}).get("min", 0))
                    totals[role]["max"] = sum(
                        m["hours"][role]["max"] for m in data.get("modules", []) if "hours" in m
                    ) + (data.get("preparation_phase", {}).get("hours", {}).get(role, {}).get("max", 0))

            totals["total_hours"] = {
                "min": sum(totals[r]["min"] for r in roles if r in totals),
                "max": sum(totals[r]["max"] for r in roles if r in totals),
            }
            totals["total_cost"] = {
                "min": round(totals["total_hours"]["min"] * hourly_rate, 2),
                "max": round(totals["total_hours"]["max"] * hourly_rate, 2),
            }

        if budget_constraint is not None and "totals" in data:
            totals = data["totals"]
            target_hours = budget_constraint / hourly_rate
            avg_hours = (totals["total_hours"]["min"] + totals["total_hours"]["max"]) / 2
            if avg_hours > 0 and abs(avg_hours - target_hours) > 0.5:
                scale = target_hours / avg_hours
                roles = ("pm", "design", "frontend", "backend", "qa")
                for role in roles:
                    if role in totals:
                        totals[role]["min"] = max(0, round(totals[role]["min"] * scale))
                        totals[role]["max"] = max(0, round(totals[role]["max"] * scale))
                for module in data.get("modules", []):
                    if "hours" in module:
                        for role in roles:
                            if role in module["hours"]:
                                module["hours"][role]["min"] = max(0, round(module["hours"][role]["min"] * scale))
                                module["hours"][role]["max"] = max(0, round(module["hours"][role]["max"] * scale))
                        module["total"] = {
                            "min": sum(module["hours"][r]["min"] for r in roles if r in module["hours"]),
                            "max": sum(module["hours"][r]["max"] for r in roles if r in module["hours"]),
                        }
                        for si in module.get("sub_items", []):
                            if isinstance(si, dict) and "hours" in si:
                                si["hours"]["min"] = max(1, round(si["hours"]["min"] * scale))
                                si["hours"]["max"] = max(1, round(si["hours"]["max"] * scale))
                if "preparation_phase" in data and "hours" in data["preparation_phase"]:
                    pp = data["preparation_phase"]
                    for role in roles:
                        if role in pp["hours"]:
                            pp["hours"][role]["min"] = max(0, round(pp["hours"][role]["min"] * scale))
                            pp["hours"][role]["max"] = max(0, round(pp["hours"][role]["max"] * scale))
                    pp["total"] = {
                        "min": sum(pp["hours"][r]["min"] for r in roles if r in pp["hours"]),
                        "max": sum(pp["hours"][r]["max"] for r in roles if r in pp["hours"]),
                    }

                totals["total_hours"] = {
                    "min": sum(totals[r]["min"] for r in roles if r in totals),
                    "max": sum(totals[r]["max"] for r in roles if r in totals),
                }
                totals["total_cost"] = {
                    "min": round(totals["total_hours"]["min"] * hourly_rate, 2),
                    "max": round(totals["total_hours"]["max"] * hourly_rate, 2),
                }

        perspectives = data.get("perspectives", [])
        if not perspectives or not isinstance(perspectives, list):
            modules = data.get("modules", [])
            module_names = [m.get("name", "") for m in modules if m.get("name")]
            generated = []
            _persp_templates = [
                ("Аналитика и отчёты", "Наглядные графики и отчёты — вы видите, что работает, и принимаете решения на основе данных"),
                ("Автоматические уведомления", "Клиенты получают напоминания, а вы — оповещения о важных событиях. Ничего не теряется."),
                ("Мобильное приложение", "Удобное приложение для телефона — ваши клиенты всегда на связи, даже в дороге"),
                ("Умные рекомендации", "Система подсказывает клиентам подходящие товары или услуги — средний чек растёт"),
                ("Рост без ограничений", "Система готова к увеличению нагрузки — когда бизнес вырастет, продукт справится"),
            ]
            for i, (title, desc) in enumerate(_persp_templates):
                if i < len(module_names):
                    desc = f"Развитие модуля «{module_names[i]}»: {desc.lower()}"
                generated.append({"title": title, "description": desc})
            data["perspectives"] = generated
            logger.info("Safety net: generated %d default perspectives", len(generated))

        stages = data.get("stages", [])
        if not stages:
            stages = []
            data["stages"] = stages

        data["stages"] = [s for s in stages if "скоупинг" not in s.get("name", "").lower() and "scoping" not in s.get("name", "").lower()]
        if design_type == "no_design":
            data["stages"] = [s for s in data["stages"] if "дизайн" not in s.get("name", "").lower()]
        stages = data["stages"]

        stage_names_lower = [s.get("name", "").lower() for s in stages]

        has_design = any("дизайн" in n for n in stage_names_lower)
        has_dev = any("разработка" in n for n in stage_names_lower)
        has_test = any("тестирован" in n or "отладк" in n or "деплой" in n or "запуск" in n for n in stage_names_lower)

        totals_data = data.get("totals", {})
        if design_type != "no_design" and not has_design:
            design_hours = (totals_data.get("design", {}).get("min", 0) + totals_data.get("design", {}).get("max", 0)) // 2
            if design_hours > 0:
                stages.insert(0, {
                    "name": "UX/UI Дизайн",
                    "tasks": [
                        {"name": "Проектирование структуры экранов и навигации", "hours": max(1, design_hours // 3)},
                        {"name": "Создание вайрфреймов ключевых страниц", "hours": max(1, design_hours // 3)},
                        {"name": "Согласование и финализация макетов", "hours": max(1, design_hours - 2 * (design_hours // 3))},
                    ]
                })

        if not has_test:
            qa_hours = (totals_data.get("qa", {}).get("min", 0) + totals_data.get("qa", {}).get("max", 0)) // 2
            if qa_hours <= 0:
                qa_hours = max(4, int(((totals_data.get("total_hours", {}).get("min", 0) + totals_data.get("total_hours", {}).get("max", 0)) / 2) * 0.1))
            stages.append({
                "name": "Тестирование и запуск",
                "tasks": [
                    {"name": "Проверка всех функций", "hours": max(1, qa_hours // 3)},
                    {"name": "Исправление ошибок", "hours": max(1, qa_hours // 3)},
                    {"name": "Запуск на рабочем сервере", "hours": max(1, qa_hours - 2 * (qa_hours // 3))},
                ]
            })

        data["stages"] = stages

        if stages:
            stages_total = sum(
                t.get("hours", 0) for s in stages for t in s.get("tasks", [])
            )
            target_total = (
                data.get("totals", {}).get("total_hours", {}).get("min", 0)
                + data.get("totals", {}).get("total_hours", {}).get("max", 0)
            ) / 2

            if stages_total > 0 and target_total > 0:
                ratio = target_total / stages_total
                if abs(ratio - 1.0) > 0.05:
                    for stage in stages:
                        for task in stage.get("tasks", []):
                            task["hours"] = max(1, round(task["hours"] * ratio))

        return data

    async def _call_api(self, prompt: str) -> str | None:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 16000,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["choices"][0]["message"]["content"]
                    else:
                        error_text = await response.text()
                        logger.error(f"ProposalCalculator API error: {response.status} - {error_text}")
                        return None
        except Exception as e:
            logger.error(f"ProposalCalculator API call failed: {e}", exc_info=True)
            return None

    def _parse_response(self, raw: str) -> dict | None:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI estimation JSON: {e}\nRaw response:\n{raw[:2000]}")
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            return None

    @staticmethod
    def _error_result(message: str) -> dict:
        return {
            "error": True,
            "error_message": message,
            "project_name": "Ошибка расчёта",
            "modules": [],
            "totals": {
                "pm": {"min": 0, "max": 0},
                "design": {"min": 0, "max": 0},
                "frontend": {"min": 0, "max": 0},
                "backend": {"min": 0, "max": 0},
                "qa": {"min": 0, "max": 0},
                "total_hours": {"min": 0, "max": 0},
                "total_cost": {"min": 0, "max": 0},
            },
            "timeline_months": {"min": 0, "max": 0},
        }
