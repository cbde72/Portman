"""Application service coordinating annotations, Goldens and safe rules."""

from .models import RuleStatus
from .rules import SafeRuleEngine, compare_values
from portman_parsers.rules import ProfileStore, RuleProfile


class TrainingService:
    def __init__(self, repository, engine=None, profile_store=None):
        self.repository = repository
        self.engine = engine or SafeRuleEngine()
        self.profile_store = profile_store or ProfileStore(repository.path.parent / "rule-profiles")

    def suggest_rule(self, annotation_id: int, created_by: str) -> int | None:
        annotation = self.repository.annotation(annotation_id)
        rule = self.engine.suggest(annotation)
        if rule is None:
            self.repository.add_training_history(annotation["document_id"], "RULE_DECLINED", created_by,
                                                 {"annotation_id": annotation_id, "reason": "no safe literal proposal"})
            return None
        return self.repository.create_rule_candidate(annotation["document_id"], annotation["parser_id"],
                                                     annotation["handler_id"], rule, (annotation_id,), created_by)

    def test_candidate(self, candidate_id: int, tested_by: str) -> dict:
        candidate = self.repository.rule_candidate(candidate_id)
        annotations = [self.repository.annotation(item) for item in candidate["annotation_ids"]]
        rows = []
        for annotation in annotations:
            actual = self.engine.execute(candidate["rule"], annotation["original_text"])
            matches = compare_values(actual, annotation["reference_value"])
            rows.append({"annotation_id": annotation["annotation_id"], "actual": actual,
                         "reference": annotation["reference_value"], "matches": matches})
        critical = any("cash_movements" in a["field_path"] and not row["matches"]
                       for a, row in zip(annotations, rows))
        result = {"rows": rows, "improved": sum(row["matches"] for row in rows),
                  "regressions": sum(not row["matches"] for row in rows),
                  "critical_cashflow_regression": critical}
        self.repository.save_rule_test(candidate_id, result, tested_by)
        return result

    def approve(self, candidate_id: int, approved_by: str, reason: str) -> int:
        latest = self.repository.latest_rule_test(candidate_id)
        if not latest or latest["result"].get("regressions") or latest["result"].get("critical_cashflow_regression"):
            raise ValueError("candidate has untested or unsafe regressions")
        version_id = self.repository.approve_rule_candidate(candidate_id, approved_by, reason)
        candidate = self.repository.rule_candidate(candidate_id)
        version = self.repository.rule_version(version_id)
        document = self.repository.document(candidate["document_id"])
        latest_run = self.repository.runs_for_document(candidate["document_id"])[-1] if self.repository.runs_for_document(candidate["document_id"]) else None
        profile = RuleProfile(
            profile_id=f"{candidate['parser_id']}.{candidate['handler_id']}.user",
            bank=document["bank"] or "comdirect", parser_id=candidate["parser_id"],
            document_type=document["document_type"] or candidate["handler_id"], handler_id=candidate["handler_id"],
            layout_variant="annotated", profile_version=version["profile_version"],
            parser_version=latest_run["parser_version"] if latest_run else "unknown",
            rules=tuple(version["rules"]), status="APPROVED", approved_by=approved_by,
            approval_reason=reason).sealed()
        self.profile_store.save(profile)
        return version_id

    def activate(self, version_id: int):
        version = self.repository.rule_version(version_id)
        candidate = self.repository.rule_candidate(version["candidate_id"])
        document = self.repository.document(candidate["document_id"])
        latest_run = self.repository.runs_for_document(candidate["document_id"])[-1] if self.repository.runs_for_document(candidate["document_id"]) else None
        profile = RuleProfile(f"{candidate['parser_id']}.{candidate['handler_id']}.user", document["bank"] or "comdirect",
                              candidate["parser_id"], document["document_type"] or candidate["handler_id"], candidate["handler_id"],
                              "annotated", version["profile_version"], latest_run["parser_version"] if latest_run else "unknown",
                              tuple(version["rules"]), approved_by=version["created_by"]).sealed()
        self.profile_store.activate(profile)
        self.repository.record_profile_activation(profile.parser_id, profile.handler_id, profile.document_type,
                                                  profile.layout_variant, version_id, profile.profile_id,
                                                  profile.profile_version, profile.profile_hash, True, "GUI user")
        self.repository.add_training_history(candidate["document_id"], "PROFILE_ACTIVATED", "GUI user", {"version_id": version_id, "profile_hash": profile.profile_hash})
        return profile

    def deactivate(self, version_id: int):
        version = self.repository.rule_version(version_id); candidate = self.repository.rule_candidate(version["candidate_id"]); document = self.repository.document(candidate["document_id"])
        self.profile_store.deactivate(candidate["parser_id"], candidate["handler_id"], document["document_type"] or candidate["handler_id"], "annotated")
        self.repository.record_profile_activation(candidate["parser_id"], candidate["handler_id"], document["document_type"] or candidate["handler_id"],
                                                  "annotated", version_id, f"{candidate['parser_id']}.{candidate['handler_id']}.user",
                                                  version["profile_version"], "deactivated", False, "GUI user")

    def reject(self, candidate_id: int, user: str, reason: str) -> None:
        self.repository.decide_rule_candidate(candidate_id, RuleStatus.REJECTED, user, reason)
