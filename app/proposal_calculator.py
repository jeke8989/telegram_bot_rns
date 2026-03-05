"""
AI-powered project estimation engine for commercial proposals.
Uses Claude Opus via OpenRouter to analyze project descriptions
and produce structured hour/cost breakdowns.

Architecture:
- AI generates ONLY modules + perspectives (no stages)
- Stages are ALWAYS built deterministically from modules in post-processing
- Standard module anchors guarantee consistent structure
"""

import aiohttp
import json
import logging
import re

logger = logging.getLogger(__name__)

_DESIGN_RE = re.compile(r'дизайн|ux|ui|wireframe|вайрфрейм|макет', re.IGNORECASE)
_PREP_RE = re.compile(r'подготовк|проектирован|архитектур|kickoff|кикофф', re.IGNORECASE)

_DEFAULT_PERSPECTIVES = [
    {"title": "Аналитика и отчёты", "description": "Наглядные графики и отчёты — вы видите, что работает, и принимаете решения на основе данных"},
    {"title": "Автоматические уведомления", "description": "Клиенты получают напоминания, а вы — оповещения о важных событиях"},
    {"title": "Мобильное приложение", "description": "Удобное приложение для телефона — ваши клиенты всегда на связи"},
    {"title": "Умные рекомендации", "description": "Система подсказывает клиентам подходящие товары или услуги — средний чек растёт"},
    {"title": "Рост без ограничений", "description": "Система готова к увеличению нагрузки — когда бизнес вырастет, продукт справится"},
]


class ProposalCalculator:
    def __init__(self, openrouter_api_key: str):
        self.api_key = openrouter_api_key
        self.model = "anthropic/claude-opus-4-5"
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
            project_description, proposal_type, budget_constraint,
            budget_currency, design_type, hourly_rate, currency,
        )

        result = await self._call_api(prompt)
        if result is None:
            return self._error_result("AI API call failed")

        parsed = self._parse_response(result)
        if parsed is None:
            return self._error_result("Failed to parse AI response")

        logger.info(
            "AI response parsed: keys=%s, modules=%d",
            list(parsed.keys()), len(parsed.get("modules", [])),
        )

        parsed = self._postprocess(parsed, design_type, hourly_rate, budget_constraint)

        if not parsed.get("perspectives"):
            parsed["perspectives"] = list(_DEFAULT_PERSPECTIVES)

        parsed["hourly_rate"] = hourly_rate
        parsed["currency"] = currency
        parsed["proposal_type"] = proposal_type
        parsed["design_type"] = design_type

        return parsed

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

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
            budget_section = (
                f"\n## STRICT Budget Constraint\n"
                f"Budget: **{budget_constraint:,.0f} {budget_currency or currency}**. "
                f"Rate: {hourly_rate} {currency}/h → target **{target_hours:,.0f}** hours.\n"
            )

        design_label = {
            "full_design": "Full UX/UI Design",
            "wireframes": "Wireframes Only",
            "no_design": "No Design",
        }.get(design_type, design_type)

        design_instruction = ""
        if design_type == "no_design":
            design_instruction = (
                "\n## CRITICAL: No Design\n"
                'Do NOT include any design module. All modules must have "stage": "dev".\n'
            )

        from math import ceil
        desc_len = len(project_description)
        mvp = proposal_type.lower() == "mvp"
        mod_min, mod_max = (3, 5) if mvp else (4, 7)
        hr_min, hr_max = (50, 100) if mvp else (80, 200)

        return f"""You are a senior technical estimator at НейроСофт — a lean web agency.
We use AI-assisted coding (Cursor AI, Copilot), ready-made boilerplates, and CRUD generators.
Stack: Next.js / React + NestJS / Python + PostgreSQL + Docker.
AI tools give us ~40 % faster frontend and ~30 % faster backend vs. industry average.
The hour norms below ALREADY include this speedup — do NOT reduce further.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Scope : **{proposal_type.upper()}**
- Design: **{design_label}**
- Rate  : **{hourly_rate} {currency}/h**
{budget_section}{design_instruction}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROJECT DESCRIPTION ({desc_len} chars)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{project_description}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ESTIMATION RULES (follow strictly)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### 1. Module count & hour budget
- {"MVP" if mvp else "Full"} project → exactly **{mod_min}–{mod_max} modules** (dev only, design is separate).
- Total dev hours target: **{hr_min}–{hr_max} h**.
- If the description is long, consolidate features into fewer, larger modules.
  NEVER create a module per paragraph — group related functionality.

### 2. Hour norms per module type
| Type | Examples | Hours |
|------|----------|-------|
| Preparation | architecture, DB schema, infra, kickoff | 8–14 |
| Auth & users | registration, login, roles, profiles | 8–14 |
| Simple CRUD | list + card + create/edit forms | 8–14 |
| Medium feature | dashboard, analytics, multi-step flows | 14–22 |
| Complex feature | real-time, billing, document workflow | 20–35 |
| Integrations (all) | each external API = 4–8h; group into ONE module | 8–20 |

### 3. Mandatory structure
1. First module MUST be **"Подготовка и проектирование"** (8–14h):
   - sub_items: architecture+DB design, infra setup, kickoff & sprint planning.
2. Group ALL external integrations (APIs, bots, payment, etc.) into ONE **"Интеграции"** module.
3. If description mentions auth/users → one **"Пользователи и авторизация"** module.
4. Remaining features → group by business domain into 1-3 modules.

### 4. What NOT to include
- No PM, QA, testing, marketing modules (they are overhead, added separately).
- No design modules (the system adds them automatically based on design type).
- No deployment/DevOps module (covered by "Подготовка").

### 5. Sub-items
- 2–5 sub_items per module, each with `name` (string) and `hours` (integer).
- Sub-item names: short, actionable Russian ("Регистрация и авторизация", "Календарь записей").
- `total` field = exact sum of sub_item hours.

### 6. Totals & timeline
- `totals.total_hours` = sum of ALL module totals.
- `totals.total_cost` = total_hours × {hourly_rate}.
- `timeline_weeks` = ceil(total_hours / 40) — calculate, do not guess.
- `team_size` = 2 for MVP, 3 for Full.

### 7. Perspectives
- 4–5 items describing **future enhancements** (not included in current scope).
- Business-friendly Russian. Each has `title` + `description`.
- Think about what would make the client want to continue development.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLE OUTPUT (for "CRM for beauty salon", Full, 2000 ₽/h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "project_name": "CRM для салона красоты",
  "project_description_short": "Система управления записями, клиентами и аналитикой",
  "modules": [
    {{
      "name": "Подготовка и проектирование",
      "description": "Архитектура, база данных, настройка инфраструктуры",
      "stage": "dev",
      "sub_items": [
        {{"name": "Проектирование архитектуры и БД", "hours": 5}},
        {{"name": "Настройка инфраструктуры и CI/CD", "hours": 4}},
        {{"name": "Kickoff и планирование спринтов", "hours": 3}}
      ],
      "total": 12
    }},
    {{
      "name": "Пользователи и авторизация",
      "description": "Регистрация, роли, профили",
      "stage": "dev",
      "sub_items": [
        {{"name": "Регистрация и авторизация", "hours": 5}},
        {{"name": "Роли и разграничение доступа", "hours": 4}},
        {{"name": "Профили пользователей", "hours": 3}}
      ],
      "total": 12
    }},
    {{
      "name": "Управление записями",
      "description": "Онлайн-запись, календарь, уведомления",
      "stage": "dev",
      "sub_items": [
        {{"name": "Календарь и слоты записи", "hours": 8}},
        {{"name": "Онлайн-запись для клиентов", "hours": 6}},
        {{"name": "Напоминания и уведомления", "hours": 4}}
      ],
      "total": 18
    }},
    {{
      "name": "Клиентская база и аналитика",
      "description": "CRM, история визитов, дашборд",
      "stage": "dev",
      "sub_items": [
        {{"name": "База клиентов с историей", "hours": 6}},
        {{"name": "Аналитический дашборд", "hours": 8}},
        {{"name": "Отчёты и экспорт", "hours": 4}}
      ],
      "total": 18
    }},
    {{
      "name": "Интеграции",
      "description": "Telegram-бот, платёжная система",
      "stage": "dev",
      "sub_items": [
        {{"name": "Telegram Bot API", "hours": 6}},
        {{"name": "Платёжный шлюз", "hours": 6}}
      ],
      "total": 12
    }}
  ],
  "totals": {{"total_hours": 72, "total_cost": 144000}},
  "timeline_weeks": 2,
  "team_size": 3,
  "perspectives": [
    {{"title": "Мобильное приложение", "description": "Удобное приложение для клиентов — запись в один клик с телефона"}},
    {{"title": "Программа лояльности", "description": "Бонусы и скидки для постоянных клиентов — повышают возвращаемость"}},
    {{"title": "Онлайн-оплата", "description": "Клиенты оплачивают услуги онлайн — меньше отмен и no-show"}},
    {{"title": "Аналитика по сотрудникам", "description": "Отслеживайте загрузку и эффективность каждого мастера"}}
  ]
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY valid JSON. No markdown, no ```, no explanations.
Keys: project_name, project_description_short, modules, totals, timeline_weeks, team_size, perspectives.
Do NOT include "stages" — they are generated automatically by the system.

FINAL CHECKLIST (verify before responding):
✓ Module count: {mod_min}–{mod_max}
✓ Total hours: {hr_min}–{hr_max}
✓ First module = "Подготовка и проектирование"
✓ All integrations in one module
✓ No PM/QA/Testing/Marketing/Design modules
✓ Every module has "stage": "dev"
✓ total = exact sum of sub_item hours
✓ totals.total_hours = sum of all module totals
✓ totals.total_cost = total_hours × {hourly_rate}
✓ timeline_weeks = ceil(total_hours / 40)
✓ All text in Russian
"""

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    @classmethod
    def _postprocess(cls, data: dict, design_type: str, hourly_rate: float,
                     budget_constraint: float | None = None) -> dict:
        modules = data.get("modules") or []

        # 1. Assign stage to each module based on name
        for m in modules:
            if not m.get("stage"):
                m["stage"] = "design" if _DESIGN_RE.search(m.get("name", "")) else "dev"
            if not m.get("sub_items"):
                m["sub_items"] = []
            for si in m["sub_items"]:
                if not isinstance(si.get("hours"), (int, float)):
                    si["hours"] = cls._normalize_hours(si.get("hours"))

        # 2. Ensure design module exists (if design_type != no_design)
        if design_type != "no_design":
            has_design = any(m.get("stage") == "design" for m in modules)
            if not has_design:
                dev_hours = sum(m.get("total", 0) for m in modules)
                if design_type == "wireframes":
                    dh = max(6, int(dev_hours * 0.12))
                    subs = [
                        {"name": "Wireframes интерфейса", "hours": max(3, dh * 2 // 3)},
                        {"name": "Схемы потоков и навигации", "hours": max(2, dh - dh * 2 // 3)},
                    ]
                else:
                    dh = max(10, int(dev_hours * 0.20))
                    subs = [
                        {"name": "Wireframes и прототипы", "hours": max(3, dh // 3)},
                        {"name": "UI-дизайн ключевых экранов", "hours": max(3, dh // 3)},
                        {"name": "Дизайн-система и гайдлайны", "hours": max(2, dh - 2 * (dh // 3))},
                    ]
                modules.insert(0, {
                    "name": "UX/UI Дизайн",
                    "description": "Проектирование интерфейса",
                    "stage": "design",
                    "sub_items": subs,
                    "total": sum(s["hours"] for s in subs),
                })
        else:
            modules = [m for m in modules if m.get("stage") != "design"]

        # 3. Ensure preparation module exists
        has_prep = any(_PREP_RE.search(m.get("name", "")) for m in modules)
        if not has_prep:
            dev_hours = sum(m.get("total", 0) for m in modules if m.get("stage") == "dev")
            ph = max(8, int(dev_hours * 0.12))
            modules.insert(
                1 if modules and modules[0].get("stage") == "design" else 0,
                {
                    "name": "Подготовка и проектирование",
                    "description": "Архитектура, база данных, настройка инфраструктуры",
                    "stage": "dev",
                    "sub_items": [
                        {"name": "Проектирование архитектуры и БД", "hours": max(3, ph // 3)},
                        {"name": "Настройка инфраструктуры и окружения", "hours": max(3, ph // 3)},
                        {"name": "Kickoff и планирование", "hours": max(2, ph - 2 * (ph // 3))},
                    ],
                    "total": ph,
                },
            )

        data["modules"] = modules

        # 4. Recalculate totals from actual module data
        for m in modules:
            m["total"] = sum(
                (si.get("hours", 0) if isinstance(si.get("hours"), (int, float)) else 0)
                for si in m.get("sub_items", []) if isinstance(si, dict)
            )
        total_hours = sum(m["total"] for m in modules)

        # 5. Apply budget constraint (scale hours proportionally)
        if budget_constraint is not None and total_hours > 0:
            target = budget_constraint / hourly_rate
            if abs(total_hours - target) > 1:
                scale = target / total_hours
                for m in modules:
                    for si in m.get("sub_items", []):
                        if isinstance(si, dict) and isinstance(si.get("hours"), (int, float)):
                            si["hours"] = max(1, round(si["hours"] * scale))
                    m["total"] = sum(
                        si.get("hours", 0) for si in m.get("sub_items", [])
                        if isinstance(si, dict)
                    )
                total_hours = sum(m["total"] for m in modules)

        data["totals"] = {
            "total_hours": total_hours,
            "total_cost": round(total_hours * hourly_rate, 2),
        }

        # 6. Build stages deterministically from modules
        data["stages"] = cls._build_stages_from_modules(modules, total_hours)

        return data

    @staticmethod
    def _build_stages_from_modules(modules: list[dict], total_hours: int) -> list[dict]:
        stages = []

        # Design stage
        design_mods = [m for m in modules if m.get("stage") == "design"]
        if design_mods:
            tasks = []
            for m in design_mods:
                for si in m.get("sub_items", []):
                    if isinstance(si, dict) and (si.get("name") or si.get("hours")):
                        tasks.append({
                            "name": si.get("name", "Задача"),
                            "hours": max(1, si.get("hours", 1)),
                            "module": m.get("name", ""),
                        })
            if tasks:
                stages.append({"name": "UX/UI Дизайн", "tasks": tasks})

        # Dev stage
        dev_mods = [m for m in modules if m.get("stage") != "design"]
        dev_tasks = []
        for m in dev_mods:
            for si in m.get("sub_items", []):
                if isinstance(si, dict) and (si.get("name") or si.get("hours")):
                    dev_tasks.append({
                        "name": si.get("name", "Задача"),
                        "hours": max(1, si.get("hours", 1)),
                        "module": m.get("name", ""),
                    })
        if dev_tasks:
            stages.append({"name": "Разработка приложения", "tasks": dev_tasks})

        # QA/Testing stage (10% of total, min 4h)
        qa_hours = max(4, int(total_hours * 0.10))
        stages.append({
            "name": "Тестирование и запуск",
            "tasks": [
                {"name": "Проверка всех функций", "hours": max(1, qa_hours // 3)},
                {"name": "Исправление ошибок", "hours": max(1, qa_hours // 3)},
                {"name": "Запуск на рабочем сервере", "hours": max(1, qa_hours - 2 * (qa_hours // 3))},
            ],
        })

        return stages

    @staticmethod
    def _normalize_hours(val) -> int:
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, dict) and ('min' in val or 'max' in val):
            return round(((val.get('min', 0) or 0) + (val.get('max', 0) or 0)) / 2)
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # API call & parsing
    # ------------------------------------------------------------------

    async def _call_api(self, prompt: str) -> str | None:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 16000,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=180),
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
            logger.error(f"Failed to parse AI estimation JSON: {e}\nRaw: {raw[:2000]}")
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
            "totals": {"total_hours": 0, "total_cost": 0},
            "timeline_weeks": 0,
        }
