from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Avg
from django.utils import timezone

from .financial import get_project_financial_summary
from .models import get_active_budget


def _to_decimal(value, default=Decimal("0.00")):
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (TypeError, InvalidOperation, ValueError):
        return default


def _format_money(value):
    return format(value.quantize(Decimal("0.01")), ".2f")


def _format_percent(value):
    return format(value.quantize(Decimal("0.01")), ".2f") + "%"


def _project_progress_ratio(project):
    avg = project.phases.aggregate(avg_progress=Avg(
        "progress_percentage"))["avg_progress"]
    if avg is None:
        return Decimal("0.00")
    avg = _to_decimal(avg)
    return max(min(avg / Decimal("100"), Decimal("1.00")), Decimal("0.00"))


def _time_progress_percent(project):
    if not project.expected_completion_date or not project.start_date:
        return None

    total_days = (project.expected_completion_date - project.start_date).days
    if total_days <= 0:
        return None

    elapsed_days = (timezone.now().date() - project.start_date).days
    return max(min(Decimal(elapsed_days) / Decimal(total_days) * 100, Decimal("100.00")), Decimal("0.00"))


def _risk_level(indicators):
    levels = []
    budget_utilization = indicators["budget_utilization"]
    forecast_variance_pct = indicators["forecast_variance_pct"]

    if budget_utilization > Decimal("110"):
        levels.append("AT_RISK")
    elif budget_utilization > Decimal("90"):
        levels.append("WATCH")

    if forecast_variance_pct > Decimal("20"):
        levels.append("AT_RISK")
    elif forecast_variance_pct > Decimal("10"):
        levels.append("WATCH")

    if indicators.get("schedule_gap") is not None:
        schedule_gap = indicators["schedule_gap"]
        if schedule_gap < Decimal("-20"):
            levels.append("AT_RISK")
        elif schedule_gap < Decimal("-10"):
            levels.append("WATCH")

    if indicators.get("spend_vs_progress_gap") is not None:
        spend_gap = indicators["spend_vs_progress_gap"]
        if spend_gap > Decimal("25"):
            levels.append("AT_RISK")
        elif spend_gap > Decimal("15"):
            levels.append("WATCH")

    if "AT_RISK" in levels:
        return "AT_RISK"
    if "WATCH" in levels:
        return "WATCH"
    return "HEALTHY"


def _build_explanation(project, actual_cost, trend_cost, contract_value, cost_ratio, margin):
    contract = _format_money(contract_value)
    actual = _format_money(actual_cost)
    trend = _format_money(trend_cost)
    return (
        "This is a trend-based estimate (not a prediction). Current actual cost is "
        f"${actual} against a ${contract} contract value, which is {_format_percent(cost_ratio)} "
        f"of the contract. Based on the current trend and phase progress, the estimate for total "
        f"cost is ${trend}. Projected margin is {_format_percent(margin)}. "
        "Groq is only used to explain the deterministic numbers already calculated in Django; "
        "it does not set the budget, forecast, or risk thresholds."
    )


def _build_groq_summary(explanation, project, risk_level, contract_value, actual_cost, trend_cost, margin, cost_ratio):
    api_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if not api_key:
        return explanation

    try:
        from groq import Groq
    except Exception:
        return explanation

    try:
        client = Groq(api_key=api_key)
        prompt = (
            "You are a project cost explainer. Use only the numbers provided below and never invent new data. "
            "Say explicitly that this is a trend-based estimate, not a prediction. Keep the explanation short, "
            "clear, and written for a construction manager."
        )
        payload = {
            "project_code": project.code,
            "project_name": project.name,
            "risk_level": risk_level,
            "contract_value": _format_money(contract_value),
            "actual_cost": _format_money(actual_cost),
            "estimated_total_cost": _format_money(trend_cost),
            "estimated_margin_percent": _format_percent(margin),
            "cost_ratio_percent": _format_percent(cost_ratio),
            "thresholds": {
                "budget_utilization": {"healthy_max": "90.00%", "watch_max": "110.00%"},
                "forecast_variance_pct": {"healthy_max": "10.00%", "watch_max": "20.00%"},
                "schedule_gap": {"healthy_min": "-10.00%", "watch_min": "-20.00%"},
                "spend_vs_progress_gap": {"healthy_max": "15.00%", "watch_max": "25.00%"},
            },
        }
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Project facts:\n{payload}\n\nWrite a short explanation."},
            ],
            temperature=0.1,
            max_tokens=180,
        )
        content = getattr(completion.choices[0].message, "content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception:
        pass

    return explanation


def get_project_risk_forecast(project):
    """
    Build a deterministic risk and trend forecast for a project using only the
    canonical financial summary and project status data. Groq is used only to
    explain the already-calculated numbers; it never decides any risk threshold
    or financial number.
    """
    financial_summary = get_project_financial_summary(project)
    contract_value = _to_decimal(project.contract_value)
    actual_cost = _to_decimal(financial_summary["expenses"]["invoiced"])

    if contract_value > 0:
        cost_ratio = (actual_cost / contract_value) * Decimal("100")
    else:
        cost_ratio = Decimal("0.00")

    progress_ratio = _project_progress_ratio(project)
    if contract_value > 0 and progress_ratio > 0:
        trend_total_cost = actual_cost / \
            progress_ratio if progress_ratio > 0 else actual_cost
    else:
        trend_total_cost = actual_cost
    trend_total_cost = max(trend_total_cost, actual_cost)

    budget = get_active_budget(project.id)
    budget_value = _to_decimal(
        budget.total_budget) if budget else contract_value
    if budget_value > 0:
        budget_utilization = actual_cost / budget_value * Decimal("100")
        forecast_variance_pct = (
            trend_total_cost - budget_value) / budget_value * Decimal("100")
    else:
        budget_utilization = Decimal("0.00")
        forecast_variance_pct = Decimal("0.00")

    phase_progress = progress_ratio * Decimal("100")
    time_progress = _time_progress_percent(project)
    indicators = {
        "budget_utilization": budget_utilization,
        "forecast_variance_pct": forecast_variance_pct,
        "time_progress": time_progress,
        "phase_progress": phase_progress if project.phases.exists() else None,
        "schedule_gap": None,
        "spend_vs_progress_gap": None,
    }
    if indicators["phase_progress"] is not None and time_progress is not None:
        indicators["schedule_gap"] = phase_progress - time_progress
    if indicators["phase_progress"] is not None:
        indicators["spend_vs_progress_gap"] = budget_utilization - \
            phase_progress

    risk_level = _risk_level(indicators)
    thresholds = {
        "budget_utilization": {"healthy_max": "90.00%", "watch_max": "110.00%"},
        "forecast_variance_pct": {"healthy_max": "10.00%", "watch_max": "20.00%"},
        "schedule_gap": {"healthy_min": "-10.00%", "watch_min": "-20.00%"},
        "spend_vs_progress_gap": {"healthy_max": "15.00%", "watch_max": "25.00%"},
    }

    estimated_profit = contract_value - trend_total_cost
    if contract_value > 0:
        estimated_margin = (estimated_profit / contract_value) * Decimal("100")
    else:
        estimated_margin = Decimal("0.00")

    explanation = _build_explanation(
        project,
        actual_cost,
        trend_total_cost,
        contract_value,
        cost_ratio,
        estimated_margin,
    )

    ai_summary = _build_groq_summary(
        explanation,
        project,
        risk_level,
        contract_value,
        actual_cost,
        trend_total_cost,
        estimated_margin,
        cost_ratio,
    )

    return {
        "project": {
            "id": str(project.id),
            "code": project.code,
            "name": project.name,
        },
        "risk_level": risk_level,
        "risk_score": float(max(budget_utilization, forecast_variance_pct)),
        "thresholds": thresholds,
        "forecast": {
            "label": "Trend-based estimate (not a prediction)",
            "estimated_total_cost": _format_money(trend_total_cost),
            "estimated_profit": _format_money(estimated_profit),
            "estimated_margin": _format_percent(estimated_margin),
            "cost_to_contract_ratio": _format_percent(cost_ratio),
        },
        "financials": {
            "contract_value": _format_money(contract_value),
            "actual_cost": _format_money(actual_cost),
            "actual_cost_ratio": _format_percent(cost_ratio),
        },
        "explanation": ai_summary,
        "factors": [
            {
                "label": "Actual cost vs contract",
                "value": _format_percent(cost_ratio),
            },
            {
                "label": "Projected margin",
                "value": _format_percent(estimated_margin),
            },
            {
                "label": "Budget utilization",
                "value": _format_percent(budget_utilization),
            },
            {
                "label": "Forecast variance",
                "value": _format_percent(forecast_variance_pct),
            },
            {
                "label": "Phase progress",
                "value": _format_percent(phase_progress),
            },
        ],
        "generated_by": "django-deterministic-financials",
    }
