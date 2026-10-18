"""Recursive exposure calculations for normalized fund holdings.
Weights are percentage points of the parent fund's NAV. Leverage above 100% is valid.
"""
from collections import defaultdict

def calculate_lookthrough(root_ticker, holdings_by_fund, max_depth=8):
    aggregated = defaultdict(float)
    paths = []
    unresolved = []

    def walk(fund, multiplier, path, depth, ancestors):
        if depth > max_depth:
            unresolved.append({"ticker": fund, "reason": "max_depth", "path": path})
            return
        holdings = holdings_by_fund.get(fund)
        if holdings is None:
            unresolved.append({"ticker": fund, "reason": "holdings_unavailable", "path": path})
            return
        for row in holdings:
            ticker = str(row.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            weight = float(row["weight_pct"]) / 100.0
            exposure = multiplier * weight
            next_path = path + [ticker]
            if row.get("is_fund", False):
                if ticker in ancestors:
                    unresolved.append({"ticker": ticker, "reason": "cycle_detected", "path": next_path})
                elif ticker in holdings_by_fund:
                    walk(ticker, exposure, next_path, depth + 1, ancestors | {ticker})
                else:
                    unresolved.append({"ticker": ticker, "reason": "fund_holdings_unavailable", "path": next_path,
                                       "exposure_pct": exposure * 100})
            else:
                aggregated[ticker] += exposure
                paths.append({"ticker": ticker, "exposure_pct": exposure * 100, "path": next_path})
    walk(root_ticker.upper(), 1.0, [root_ticker.upper()], 0, {root_ticker.upper()})
    totals = [{"ticker": t, "exposure_pct": round(v * 100, 6),
               "multiple": round(v, 6)} for t, v in sorted(aggregated.items(),
                  key=lambda item: abs(item[1]), reverse=True)]
    return {"root_ticker": root_ticker.upper(), "holdings": totals,
            "paths": paths, "unresolved": unresolved}
