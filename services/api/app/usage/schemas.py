"""Serialisation of the usage report (contracts/usage.yaml ``UsageReport``)."""

from __future__ import annotations

from typing import Any

from app.pricing.engine import fmt6
from app.usage.service import Report


def report_json(report: Report) -> dict[str, Any]:
    return {
        "window": {"from": report.start.isoformat(), "to": report.end.isoformat()},
        "rows": [
            {
                "feature": row.feature,
                "event_count": row.event_count,
                "raw_cost_usd": fmt6(row.raw_cost_usd),
                "billable_cost_usd": fmt6(row.billable_cost_usd),
                "details": [
                    {
                        "feature_key": d.feature_key,
                        "event_count": d.event_count,
                        "raw_cost_usd": fmt6(d.raw_cost_usd),
                        "billable_cost_usd": fmt6(d.billable_cost_usd),
                    }
                    for d in row.details
                ],
            }
            for row in report.rows
        ],
        "total_raw_cost_usd": fmt6(report.total_raw_cost_usd),
        "total_billable_cost_usd": fmt6(report.total_billable_cost_usd),
    }
