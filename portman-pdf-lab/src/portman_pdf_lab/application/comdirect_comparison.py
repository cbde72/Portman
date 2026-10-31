"""Independent side-by-side execution of both comdirect implementations."""

from time import perf_counter_ns

from portman_parsers.plugins import ComdirectFinanzreportPlugin, ComdirectPlugin, ComdirectPPPlugin
from portman_parsers.validation import validate_parsed_document
from portman_parsers.rules import ProfileStore, RuleEngine, RuleMode


def _first(sequence):
    return sequence[0] if sequence else None


def _projection(result):
    event = _first(result.events)
    trade = _first(event.trades) if event else None
    cash = _first(event.cash_movements) if event else None
    security = _first(event.security_movements) if event else None
    tax = _first(event.tax_events) if event else None
    return {
        "detection.handler": result.handler_id,
        "security.name": trade.security_name if trade else None,
        "security.isin": trade.isin if trade else tax.isin if tax else security.security_id if security else None,
        "security.wkn": trade.wkn if trade else None,
        "security.quantity": trade.quantity if trade else security.quantity if security else None,
        "trade.price": trade.price if trade else None,
        "trade.market_value": trade.market_value if trade else None,
        "trade.settlement": trade.settlement_amount if trade else cash.amount if cash else None,
        "cash.amount": cash.amount if cash else None,
        "cash.status": cash.status if cash else None,
        "tax.components": tuple((x.kind, x.amount, x.currency) for x in tax.components) if tax else (),
        "tax.advance_before_partial_exemption": tax.advance_before_partial_exemption if tax else None,
        "fees": tuple((x.subcategory, x.amount, x.currency) for x in event.fee_events) if event else (),
        "evidence.count": len(result.evidence),
        "issues.count": len(result.issues),
        "events.count": len(result.events),
        "accounts.count": len(result.accounts),
        "depot_links.count": len(result.depot_account_links),
    }


def compare_comdirect_parsers(document, profile_store: ProfileStore | None = None):
    """Return copy-friendly rows; agreement is deliberately not a reference score."""
    pp = ComdirectPPPlugin()
    pp_detection = _first(pp.detect(document))
    main_plugin = ComdirectFinanzreportPlugin() if pp_detection and pp_detection.handler_id == "finanzreport" else ComdirectPlugin()
    main_detection = _first(main_plugin.detect(document))

    variants = {}
    for name, plugin, detection in (("portman", main_plugin, main_detection), ("portfolio_performance_python", pp, pp_detection)):
        started = perf_counter_ns()
        if detection is None:
            variants[name] = {"detection": None, "result": None, "runtime_ns": perf_counter_ns() - started,
                              "issues": ("UNSUPPORTED_DOCUMENT",)}
            continue
        result = plugin.parse(document, detection)
        variants[name] = {"detection": detection, "result": result,
                          "runtime_ns": perf_counter_ns() - started,
                          "issues": tuple(x.code for x in validate_parsed_document(result))}

    left = _projection(variants["portman"]["result"]) if variants["portman"]["result"] else {}
    right = _projection(variants["portfolio_performance_python"]["result"]) if variants["portfolio_performance_python"]["result"] else {}
    extended_values = {}
    store = profile_store
    for name, key in (("portman", "portman_extended"), ("portfolio_performance_python", "portfolio_performance_python_extended")):
        entry = variants[name]; projected = dict(left if name == "portman" else right); decisions = ()
        if store and entry["detection"] and entry["result"]:
            detection = entry["detection"]
            profile = store.active(detection.plugin_id, detection.handler_id, detection.document_type, "annotated", detection.plugin_version)
            overlay = RuleEngine().apply(entry["result"], document.text, profile, RuleMode.EXTENDED if profile else RuleMode.STANDARD)
            decisions = overlay.decisions
            for decision in decisions:
                projected[decision.field_path] = decision.effective_value
        extended_values[key] = projected
        variants[key] = {"decisions": decisions}
    fields = sorted(left.keys() | right.keys())
    fields = sorted(set(fields) | set(extended_values["portman_extended"]) | set(extended_values["portfolio_performance_python_extended"]))
    rows = tuple({"field": field, "portman": left.get(field), "portman_extended": extended_values["portman_extended"].get(field),
                  "portfolio_performance_python": right.get(field), "portfolio_performance_python_extended": extended_values["portfolio_performance_python_extended"].get(field),
                  "matches": left.get(field) == right.get(field), "is_confirmed_reference": False}
                 for field in fields)
    rows += ({"field": "runtime_ns", "portman": variants["portman"]["runtime_ns"],
              "portfolio_performance_python": variants["portfolio_performance_python"]["runtime_ns"],
              "matches": False, "is_confirmed_reference": False},)
    return {"rows": rows,
            "portman_detection": variants["portman"]["detection"],
            "portfolio_performance_detection": variants["portfolio_performance_python"]["detection"],
            "portman_issues": variants["portman"]["issues"],
            "portfolio_performance_issues": variants["portfolio_performance_python"]["issues"],
            "portman_rule_decisions": variants["portman_extended"]["decisions"],
            "portfolio_performance_rule_decisions": variants["portfolio_performance_python_extended"]["decisions"],
            "agreement_is_not_reference": True}
