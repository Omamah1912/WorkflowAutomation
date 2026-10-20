"""Loads rule YAML files and evaluates them. Each rule names a generic check function below;
all limits and lists come from the YAML `params`, never from Python constants.

A check receives (ctx, params) and returns (status, message, expected, actual) where
status is 'pass' | 'fail' | 'not_applicable'.
ctx = {'doc': Document, 'track': Track, 'records': [cross-record facts], 'thresholds': dict}
"""
from functools import lru_cache

from state import RuleResult
from tools import units
from tools.config import load_yaml

NA = "not_applicable"


@lru_cache(maxsize=4)
def load_rules(relative_path: str) -> dict:
    return load_yaml(relative_path)


def evaluate(relative_path: str, ctx: dict) -> list[RuleResult]:
    ruleset = load_rules(relative_path)
    results = []
    for rule in ruleset["rules"]:
        applies_to = rule.get("params", {}).get("applies_to") or ruleset.get("applies_to")
        doc_type = ctx["doc"].doc_type
        if applies_to and doc_type not in applies_to:
            status, message, expected, actual = NA, f"not applicable to {doc_type}", None, None
        elif rule.get("scope") == "primary" and not ctx.get("is_primary", True):
            status, message, expected, actual = NA, "announcement rule: judged on the primary track only", None, None
        else:
            status, message, expected, actual = CHECKS[rule["check"]](ctx, rule.get("params", {}))
        results.append(RuleResult(
            rule_id=rule["id"], status=status,
            passed=None if status == NA else status == "pass",
            severity=rule["severity"], message=message, expected=expected, actual=actual,
            source_clause=rule.get("source_clause", ""), verify=bool(rule.get("verify", False)),
            fields=rule.get("fields", []), suggested_fix=rule.get("suggested_fix", ""),
        ))
    return results


# ------------------------------------------------------------------ helpers

def _field(ctx, name):
    return ctx["track"].get(name)


def _value(ctx, name):
    f = _field(ctx, name)
    return f.value if f else None


def _fmt(n) -> str:
    return f"{n:,.2f}".rstrip("0").rstrip(".") if isinstance(n, (int, float)) else str(n)


# ------------------------------------------------------------------ dividend checks

def unit_type_is(ctx, params):
    wrong, checked = [], []
    for name, expected_type in params["expected"].items():
        f = _field(ctx, name)
        if f is None or f.value in (None, 0):
            continue  # nothing declared -> nothing to type-check
        checked.append(name)
        if f.unit_type != expected_type:
            wrong.append(f"{name} is '{f.unit}' ({f.unit_type}), expected {expected_type}")
    if not checked:
        return NA, "no cash dividend or bonus declared", params["expected"], None
    if wrong:
        return "fail", "; ".join(wrong), params["expected"], {n: _field(ctx, n).unit_type for n in checked}
    return "pass", f"unit types correct for {', '.join(checked)}", params["expected"], None


def shares_issued_within_outstanding(ctx, params):
    outstanding = _value(ctx, "shares_outstanding")
    base = _value(ctx, "eligible_shares") or outstanding  # shares the per-share figure applies to
    to_issue = 0.0
    for name in ("cash_dividend", "bonus_shares"):
        f = _field(ctx, name)
        if f and f.unit_type == "share_ratio" and f.value:
            if not base:
                return "fail", f"{name} issues shares but the share base is unknown", None, None
            to_issue += f.value * base
    if to_issue == 0:
        return "pass", "no new shares to be issued", None, 0
    if not outstanding:
        return "fail", f"{_fmt(to_issue)} shares to issue but shares outstanding unknown", None, to_issue
    limit = outstanding * params["max_multiple_of_outstanding"]
    multiple = to_issue / outstanding
    if to_issue > limit:
        return ("fail", f"issues {_fmt(to_issue)} shares = ~{multiple:.1f}x the {_fmt(outstanding)} shares outstanding",
                f"<= {_fmt(limit)}", to_issue)
    return "pass", f"issues {_fmt(to_issue)} shares ({multiple:.2f}x outstanding)", f"<= {_fmt(limit)}", to_issue


def rs_equals_percent_of_face(ctx, params):
    rs, pct, face = _field(ctx, "cash_dividend"), _field(ctx, "cash_dividend_percent"), _field(ctx, "face_value")
    if not (rs and pct and face) or rs.unit_type != "currency_per_share" or not pct.value:
        return NA, "needs Rs per share, percentage and face value", None, None
    if rs.derived_from:
        return NA, "Rs per share was itself computed from the percentage", None, None
    if face.evidence.doc_id == ctx["doc"].doc_id:
        return NA, "face value was derived from this same filing (no independent check)", None, None
    expected = units.percent_to_rs_per_share(pct.value, face.value)
    if abs(expected - rs.value) <= params["tolerance_rs"]:
        return "pass", f"Rs {_fmt(rs.value)} = {_fmt(pct.value)}% x Rs {_fmt(face.value)}", expected, rs.value
    return "fail", f"Rs {_fmt(rs.value)} != {_fmt(pct.value)}% x face value Rs {_fmt(face.value)} = Rs {_fmt(expected)}", expected, rs.value


def percent_only_converted(ctx, params):
    rs, pct = _field(ctx, "cash_dividend"), _field(ctx, "cash_dividend_percent")
    if not pct or not pct.value:
        return NA, "no percentage dividend", None, None
    if rs and not rs.derived_from:
        return NA, "Rs per share stated in the filing", None, None
    if rs:
        return "pass", f"converted {_fmt(pct.value)}% to Rs {_fmt(rs.value)} per share using face value", None, rs.value
    return "fail", f"percent-only dividend ({_fmt(pct.value)}%) and face value unknown: cannot convert to Rs per share", "face value", None


def credit_matches_declaration(ctx, params):
    me = ctx["doc"]
    cash = _value(ctx, "cash_dividend")
    if cash is None:
        return "fail", "credited amount not found", None, None
    if not (me.symbol and me.period and me.period.value):
        return NA, "company or period unknown: cannot pair with a declaration", None, cash
    matches = [r for r in ctx["records"] if r["doc_id"] != me.doc_id and r["symbol"] == me.symbol
               and r["period"] == me.period.value and r["doc_type"] in params["declaration_types"]
               and r.get("cash_dividend")]
    if not matches:
        return NA, f"no declaration for {me.symbol} period {me.period.value} in the processed records", None, cash
    declared = matches[0]["cash_dividend"]
    if abs(declared - cash) <= params["tolerance_rs"]:
        return "pass", f"credited Rs {_fmt(cash)} = declared Rs {_fmt(declared)} ({matches[0]['doc_id']})", declared, cash
    return "fail", f"credited Rs {_fmt(cash)} but declared Rs {_fmt(declared)} in {matches[0]['doc_id']}", declared, cash


def ex_price_consistent(ctx, params):
    prev, ex, cash = _value(ctx, "prev_close_price"), _value(ctx, "ex_price"), _value(ctx, "cash_dividend")
    if prev is None or ex is None or cash is None:
        return NA, "previous close and ex-price not both supplied", None, None
    expected = prev - cash
    if abs(expected - ex) <= params["tolerance_rs"]:
        return "pass", f"ex-price {_fmt(ex)} = {_fmt(prev)} - {_fmt(cash)}", expected, ex
    return "fail", f"ex-price {_fmt(ex)} != previous close {_fmt(prev)} - entitlement {_fmt(cash)}", expected, ex


def payout_vs_profit(ctx, params):
    cash, shares, profit = (_field(ctx, n) for n in ("cash_dividend", "shares_outstanding", "profit_after_tax"))
    if not (cash and shares and profit) or cash.unit_type != "currency_per_share" or not cash.value:
        return NA, "needs cash dividend, shares outstanding and profit", None, None
    payout = cash.value * shares.value
    limit = profit.value * params["max_payout_to_profit"]
    ratio = payout / profit.value if profit.value else float("inf")
    if profit.value > 0 and payout <= limit:
        return "pass", f"payout Rs {_fmt(payout)} is {ratio:.0%} of profit Rs {_fmt(profit.value)}", f"<= {_fmt(limit)}", payout
    return "fail", f"payout Rs {_fmt(payout)} vs profit Rs {_fmt(profit.value)} ({ratio:.0%})", f"<= {_fmt(limit)}", payout


def change_vs_previous(ctx, params):
    me, cash = ctx["doc"], _value(ctx, "cash_dividend")
    if not cash or not (me.symbol and me.period and me.period.value):
        return NA, "no cash dividend or company/period unknown", None, cash
    earlier = sorted((r for r in ctx["records"] if r["symbol"] == me.symbol and r["doc_type"] == me.doc_type
                      and r["period"] and r["period"] < me.period.value and r.get("cash_dividend")),
                     key=lambda r: r["period"])
    if not earlier:
        return NA, f"no earlier {me.doc_type} for {me.symbol} in the processed records", None, cash
    prev = earlier[-1]
    ratio = max(cash, prev["cash_dividend"]) / min(cash, prev["cash_dividend"])
    limit = ctx["thresholds"][params["threshold_key"]]
    msg = f"Rs {_fmt(cash)} vs Rs {_fmt(prev['cash_dividend'])} for {prev['period']} ({prev['doc_id']}): {ratio:.2f}x"
    return ("pass" if ratio <= limit else "fail"), msg, f"<= {limit}x", round(ratio, 3)


def announcement_items_present(ctx, params):
    missing = [i for i in params["items"] if not _value(ctx, i)]
    if missing:
        return "fail", "missing announcement items: " + ", ".join(m.replace("item_", "") for m in missing), params["items"], missing
    return "pass", "all five announcement items present", params["items"], []


def book_closure_ordered(ctx, params):
    announced, start, end = (_value(ctx, n) for n in ("announcement_date", "book_closure_from", "book_closure_to"))
    if not (start and end):
        return NA, "no book-closure dates", None, None
    if start > end:
        return "fail", f"book closure starts {start} after it ends {end}", "from <= to", [start, end]
    if announced and start <= announced:
        return "fail", f"book closure {start} is not after the announcement {announced}", f"> {announced}", start
    return "pass", f"book closure {start} to {end}, after announcement {announced or 'unknown'}", None, [start, end]


# ------------------------------------------------------------------ CSV checks

def relevance_by_type(ctx, params):
    t = ctx["doc"].doc_type
    if t in params["relevant_types"]:
        return "pass", f"'{t}' is relevant", True, ctx["doc"].relevance
    if t in params["irrelevant_types"]:
        return "pass", f"'{t}' is admin / irrelevant", False, ctx["doc"].relevance
    return "fail", f"document type '{t}' is not in the relevance lists", None, t


def required_metadata(ctx, params):
    doc = ctx["doc"]
    required = params["required"].get(doc.source, [])
    missing = [k for k in required if not str(doc.metadata.get(k, "")).strip()]
    bad_dates = [k for k in params["date_fields"] if k in doc.metadata and not _is_iso(doc.metadata[k])]
    if missing or bad_dates:
        return "fail", f"missing: {missing or '-'}; non-ISO dates: {bad_dates or '-'}", required, None
    return "pass", "required metadata present, dates ISO 8601", required, None


def _is_iso(value) -> bool:
    return bool(value) and str(value)[:10] == units.parse_date(str(value)[:10])


def not_duplicate(ctx, params):
    doc = ctx["doc"]
    if doc.duplicate_of:
        return "fail", f"duplicate of {doc.duplicate_of}: {doc.duplicate_reason}", None, doc.duplicate_of
    return "pass", "no duplicate found", None, None


def stream_agrees_with_legacy(ctx, params):
    doc = ctx["doc"]
    if not doc.legacy_stream:
        return NA, "no legacy stream", None, None
    if doc.legacy_stream == doc.stream:
        return "pass", f"agrees with legacy '{doc.legacy_stream}'", doc.stream, doc.legacy_stream
    return "fail", f"agent routed to '{doc.stream}', legacy said '{doc.legacy_stream}'", doc.stream, doc.legacy_stream


CHECKS = {f.__name__: f for f in [
    unit_type_is, shares_issued_within_outstanding, rs_equals_percent_of_face, percent_only_converted,
    credit_matches_declaration, ex_price_consistent, payout_vs_profit, change_vs_previous,
    announcement_items_present, book_closure_ordered,
    relevance_by_type, required_metadata, not_duplicate, stream_agrees_with_legacy,
]}
