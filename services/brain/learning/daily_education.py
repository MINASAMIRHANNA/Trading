from typing import Dict
from datetime import date


def build_daily_lesson(
    decision: Dict,
    strategy_stats: Dict,
    current_regime: str | None = None,
) -> Dict:
    """
    Generate a single daily educational lesson based on today's context.
    """

    lesson = {
        "date": str(date.today()),
        "title": "",
        "explanation": "",
        "takeaway": "",
    }

    # -------------------------
    # Case 1: DO NOT TRADE
    # -------------------------
    if decision.get("decision") == "DO_NOT_TRADE":
        progress = decision.get("data_progress", 0)

        lesson["title"] = "Capital Preservation is a Position"
        lesson["explanation"] = (
            "Today the system recommended not trading. "
            "This usually happens when data is insufficient or "
            "market conditions are unfavorable."
        )

        if progress < 1.0:
            lesson["explanation"] += (
                f" Your dataset is about {int(progress * 100)}% ready."
            )

        lesson["takeaway"] = (
            "Avoid forcing trades. Staying flat is often the best decision "
            "until conditions improve or more data is collected."
        )

        return lesson

    # -------------------------
    # Case 2: Trade Selectively
    # -------------------------
    strategy = decision.get("recommended_strategy")

    lesson["title"] = "Selective Trading Beats Overtrading"
    lesson["explanation"] = (
        f"The system recommends trading selectively using the strategy "
        f"'{strategy}'. This means your edge exists, but only in specific situations."
    )

    if current_regime:
        lesson["explanation"] += (
            f" The current market regime is '{current_regime}', "
            "which historically supports this approach."
        )

    lesson["takeaway"] = (
        "Focus only on high-quality setups that match the recommended strategy. "
        "Skip everything else."
    )

    return lesson
