"""
AI-powered project estimation engine for commercial proposals.
Uses Claude Sonnet 4.5 via OpenRouter to analyze project descriptions
and produce structured hour/cost breakdowns.
"""

import aiohttp
import json
import logging
import re

logger = logging.getLogger(__name__)

ESTIMATION_NORMS = """
## Reference Estimation Norms

Typical hour ranges per feature complexity:
- Simple CRUD page (list + card + create/edit): 15-30 hours
- Medium complexity module (dashboard, analytics, charts): 40-80 hours
- Complex module (real-time chat, billing, document flow): 70-140 hours
- Authentication & registration: 15-30 hours
- Landing page: 30-60 hours
- Admin panel with roles: 60-150 hours
- Mobile app (single role, 5-8 screens): 100-200 hours
- Integration with external API: 10-30 hours per integration
- Preparation phase (architecture, DB design, tech docs): 50-120 hours

## MVP vs Full estimation
- MVP: Focus on core features only. Reduce scope by ~40-50%.
  Team: 2-3 people. Timeline: 1-3 weeks.
- Full: Complete feature set with all described functionality.
  Team: 3-5 people. Timeline: 4-16 weeks.

## Timeline Calculation Rules
- Calculate timeline_weeks based on total hours / team capacity.
- MVP team: 2-3 people * 40h/week = 80-120h/week capacity.
- Full project team: 3-5 people * 40h/week = 120-200h/week capacity.

## Design options
- Full Design: Full UX/UI design hours (wireframes + mockups + design system)
- Wireframes Only: ~40% of full design hours
- No Design: Zero design hours
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

        logger.info(
            "AI response parsed: keys=%s, modules=%d, stages=%d",
            list(parsed.keys()),
            len(parsed.get("modules", [])),
            len(parsed.get("stages", [])),
        )

        parsed = self._apply_multipliers(parsed, design_type, hourly_rate, budget_constraint)

        if "perspectives" not in parsed or not parsed["perspectives"]:
            parsed["perspectives"] = [
                {"title": "Аналитика и отчёты", "description": "Наглядные графики и отчёты — вы видите, что работает, и принимаете решения на основе данных"},
                {"title": "Автоматические уведомления", "description": "Клиенты получают напоминания, а вы — оповещения о важных событиях"},
                {"title": "Мобильное приложение", "description": "Удобное приложение для телефона — ваши клиенты всегда на связи"},
                {"title": "Умные рекомендации", "description": "Система подсказывает клиентам подходящие товары или услуги — средний чек растёт"},
                {"title": "Рост без ограничений", "description": "Система готова к увеличению нагрузки — когда бизнес вырастет, продукт справится"},
            ]

        if "stages" not in parsed or not parsed["stages"]:
            self._generate_fallback_stages(parsed, design_type)

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
Adjust scope to hit this target precisely. Do NOT exceed or undershoot the budget.
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
The client chose NO DESIGN. Do NOT include any design work — not even wireframes or mockups.
Do NOT include a "UX/UI Дизайн" stage.
"""

        if design_type == "no_design":
            design_stage_instruction = '1. "UX/UI Дизайн" — NOT needed (no_design). Do NOT include this stage.'
        elif design_type == "wireframes":
            design_stage_instruction = '1. "UX/UI Дизайн" — MANDATORY. Include wireframe tasks.'
        else:
            design_stage_instruction = '1. "UX/UI Дизайн" — MANDATORY. Include full design tasks.'

        return f"""You are an expert software project estimator for a web/mobile development agency.
Analyze the project description and produce a detailed, structured estimation.

{ESTIMATION_NORMS}

## Our Tech Stack
**Frontend:** Next.js, React, TypeScript, Redux Toolkit, Tailwind CSS
**Backend:** NestJS, TypeORM, PostgreSQL, Redis, Socket.io
**Infrastructure:** Docker, CI/CD, Cloud deployments

We have ready-made templates, auth modules, admin panels, and API scaffolding.

## AI-Assisted Development
Our team uses AI tools (Cursor AI, GitHub Copilot):
- **Frontend takes 40% less time** (0.6x multiplier already applied in your estimates)
- **Backend takes 30% less time** (0.7x multiplier already applied in your estimates)
- Apply these speedups to ALL hour estimates from the start.

## Input Parameters
- Proposal type: **{proposal_type.upper()}**
- Design approach: **{design_label}**
- Hourly rate: **{hourly_rate} {currency}/hour**
{budget_section}
{no_design_instruction}

## Project Description
---
{project_description}
---

## Your Task

1. Break the project into logical modules. Name them in SIMPLE BUSINESS LANGUAGE:
   Good: "Личный кабинет", "Каталог товаров", "Система оплаты"
   Bad: "API Gateway", "Auth Module", "WebSocket Service"
2. For each module, list 3-8 specific work items (sub_items). Each has a name and a SINGLE hours value (not min/max).
   The module total = sum of sub_item hours.
3. Include a "Подготовка и проектирование" module (architecture, DB design, meetings).
4. Calculate totals: total_hours (sum of all module totals), total_cost (total_hours * hourly_rate).
5. Estimate timeline_weeks (single number). MVP: 1-3 weeks. Full: calculate from hours/team.
6. Estimate team_size (single number).
7. Generate a short project_name (2-5 words in Russian).
8. project_description_short: 1-2 sentences in simple Russian about what the project does for the business.

## CRITICAL: Output Format

Return ONLY valid JSON (no markdown, no ```json blocks). Use this EXACT structure:

{{
    "project_name": "Short name in Russian",
    "project_description_short": "1-2 sentences in Russian",
    "modules": [
        {{
            "name": "Module name in Russian",
            "description": "Short description in Russian",
            "sub_items": [
                {{"name": "Work item in Russian", "hours": 12}},
                {{"name": "Work item in Russian", "hours": 8}}
            ],
            "total": 20
        }}
    ],
    "totals": {{
        "total_hours": 150,
        "total_cost": 7500.0
    }},
    "timeline_weeks": 4,
    "team_size": 3,
    "notes": ["Note 1", "Note 2"],
    "perspectives": [
        {{"title": "Short title in Russian", "description": "Business value in Russian"}}
    ],
    "stages": [
        {{
            "name": "UX/UI Дизайн",
            "tasks": [
                {{"name": "Task in Russian", "hours": 16}}
            ]
        }},
        {{
            "name": "Разработка приложения",
            "tasks": [
                {{"name": "Task in Russian", "hours": 20, "module": "Module name"}},
                {{"name": "Task in Russian", "hours": 12, "module": "Module name"}}
            ]
        }},
        {{
            "name": "Тестирование и запуск",
            "tasks": [
                {{"name": "Task in Russian", "hours": 8, "module": "Module name"}},
                {{"name": "Task in Russian", "hours": 4}}
            ]
        }}
    ]
}}

IMPORTANT RULES:
- ALL hours are SINGLE integers, NOT min/max objects.
- total_cost = total_hours * {hourly_rate}
- All text MUST be in Russian.
- Each sub_item is {{"name": "string", "hours": integer}}.
- Module total = sum of its sub_items hours.
- totals.total_hours = sum of all module totals.
- perspectives: 4-6 items, business language, no technical jargon.
- stages MUST contain:
  {design_stage_instruction}
  2. "Разработка приложения" — MANDATORY. Tasks grouped by module (use "module" field).
  3. "Тестирование и запуск" — MANDATORY.
- Tasks in stages have SINGLE "hours" integer.
- Sum of all stage task hours ≈ totals.total_hours.
- Each task in "Разработка" and "Тестирование" MUST have "module" field matching a module name.

Ensure all numbers are realistic and consistent. Double-check math.
"""

    @staticmethod
    def _apply_multipliers(data: dict, design_type: str, hourly_rate: float, budget_constraint: float | None = None) -> dict:
        """Post-process: enforce budget constraint if set, fix stages."""
        for module in data.get("modules", []):
            sub_items = module.get("sub_items", [])
            module["total"] = sum(
                (si.get("hours", 0) if isinstance(si.get("hours"), (int, float)) else 0)
                for si in sub_items if isinstance(si, dict)
            )

        total_hours = sum(m.get("total", 0) for m in data.get("modules", []))
        data["totals"] = {
            "total_hours": total_hours,
            "total_cost": round(total_hours * hourly_rate, 2),
        }

        if budget_constraint is not None and total_hours > 0:
            target_hours = budget_constraint / hourly_rate
            if abs(total_hours - target_hours) > 1:
                scale = target_hours / total_hours
                for module in data.get("modules", []):
                    for si in module.get("sub_items", []):
                        if isinstance(si, dict) and isinstance(si.get("hours"), (int, float)):
                            si["hours"] = max(1, round(si["hours"] * scale))
                    module["total"] = sum(
                        si.get("hours", 0) for si in module.get("sub_items", []) if isinstance(si, dict)
                    )
                total_hours = sum(m.get("total", 0) for m in data.get("modules", []))
                data["totals"] = {
                    "total_hours": total_hours,
                    "total_cost": round(total_hours * hourly_rate, 2),
                }

        # --- Fix stages ---
        stages = data.get("stages", [])
        data["stages"] = [
            s for s in stages
            if "скоупинг" not in s.get("name", "").lower() and "scoping" not in s.get("name", "").lower()
        ]
        if design_type == "no_design":
            data["stages"] = [s for s in data["stages"] if "дизайн" not in s.get("name", "").lower()]

        stage_names_lower = [s.get("name", "").lower() for s in data["stages"]]
        has_test = any("тестирован" in n or "запуск" in n for n in stage_names_lower)
        if not has_test:
            qa_hours = max(4, int(total_hours * 0.1))
            data["stages"].append({
                "name": "Тестирование и запуск",
                "tasks": [
                    {"name": "Проверка всех функций", "hours": max(1, qa_hours // 3)},
                    {"name": "Исправление ошибок", "hours": max(1, qa_hours // 3)},
                    {"name": "Запуск на рабочем сервере", "hours": max(1, qa_hours - 2 * (qa_hours // 3))},
                ]
            })

        stages_total = sum(t.get("hours", 0) for s in data["stages"] for t in s.get("tasks", []))
        if stages_total > 0 and total_hours > 0:
            ratio = total_hours / stages_total
            if abs(ratio - 1.0) > 0.05:
                for stage in data["stages"]:
                    for task in stage.get("tasks", []):
                        task["hours"] = max(1, round(task["hours"] * ratio))

        return data

    @staticmethod
    def _generate_fallback_stages(data: dict, design_type: str):
        """Generate stages from modules when AI didn't provide them."""
        stages = []
        total_hours = data.get("totals", {}).get("total_hours", 0)

        if design_type != "no_design":
            dh = max(3, int(total_hours * 0.15))
            stages.append({
                "name": "UX/UI Дизайн",
                "tasks": [
                    {"name": "Проектирование структуры экранов и навигации", "hours": max(1, dh // 3)},
                    {"name": "Создание вайрфреймов ключевых страниц", "hours": max(1, dh // 3)},
                    {"name": "Согласование и финализация макетов", "hours": max(1, dh - 2 * (dh // 3))},
                ]
            })

        dev_tasks = []
        for mod in data.get("modules", []):
            mod_name = mod.get("name", "Модуль")
            for si in mod.get("sub_items", []):
                if isinstance(si, dict):
                    dev_tasks.append({
                        "name": si.get("name", "Задача"),
                        "hours": max(1, si.get("hours", 2)),
                        "module": mod_name,
                    })
            if not mod.get("sub_items"):
                dev_tasks.append({
                    "name": f"Разработка модуля {mod_name}",
                    "hours": max(2, mod.get("total", 8)),
                    "module": mod_name,
                })
        stages.append({
            "name": "Разработка приложения",
            "tasks": dev_tasks or [{"name": "Основная разработка", "hours": max(4, int(total_hours * 0.7))}],
        })

        qa_hours = max(4, int(total_hours * 0.1))
        stages.append({
            "name": "Тестирование и запуск",
            "tasks": [
                {"name": "Проверка всех функций", "hours": max(1, qa_hours // 3)},
                {"name": "Исправление ошибок", "hours": max(1, qa_hours // 3)},
                {"name": "Запуск на рабочем сервере", "hours": max(1, qa_hours - 2 * (qa_hours // 3))},
            ]
        })

        data["stages"] = stages

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
                "total_hours": 0,
                "total_cost": 0,
            },
            "timeline_weeks": 0,
        }
