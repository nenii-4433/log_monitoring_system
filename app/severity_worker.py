import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sklearn.pipeline import Pipeline

from app.config import Settings, get_settings
from app.llm_severity import (
    LayerDecision,
    predict_with_local_llm,
    should_use_llm_fallback,
)
from app.severity import predict_severity_from_rules
from app.severity_context import ContextSnapshot, assess_severity_context
from app.severity_nlp import (
    LabeledExample,
    load_approved_examples,
    predict_with_nlp,
    train_severity_classifier,
)

logger = logging.getLogger("severity_worker")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MAX_LLM_ATTEMPTS = 3
_MAX_ERROR_DETAIL_LENGTH = 200


def _safe_error_detail(error: Exception) -> str:
    detail = str(error).replace("\r", " ").replace("\n", " ").strip()
    if not detail:
        return "No additional error detail."
    return detail[:_MAX_ERROR_DETAIL_LENGTH]


class SeverityWorker:
    def __init__(
        self,
        settings: Settings,
        classifier: Pipeline | None,
        client: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.classifier = classifier
        self.client = client
        self.rpc_url = (
            f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc"
        )
        self.headers = {
            "apikey": settings.supabase_secret_key,
            "Authorization": f"Bearer {settings.supabase_secret_key}",
            "Content-Type": "application/json",
        }

    async def _rpc(self, function: str, payload: dict[str, object]) -> Any:
        response = await self.client.post(
            f"{self.rpc_url}/{function}",
            headers=self.headers,
            json=payload,
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

    async def process_one(self) -> bool:
        claimed = await self._rpc(
            "claim_log_for_severity_prediction",
            {},
        )
        if not isinstance(claimed, list):
            raise RuntimeError("Queue claim returned an invalid response")
        if not claimed:
            return False

        row = claimed[0]
        if not isinstance(row, dict):
            raise RuntimeError("Queue claim returned an invalid log record")

        try:
            prediction = await self._predict(row)
        except (RuntimeError, ValueError, TypeError) as error:
            await self._handle_prediction_error(row, error)
            return True

        await self._rpc(
            "finish_log_severity_prediction",
            {
                "p_message_id": row["message_id"],
                "p_log_id": row["log_id"],
                "p_status": "complete",
                "p_severity": prediction["severity"],
                "p_confidence": prediction["confidence"],
                "p_reason": prediction["reason"],
                "p_method": prediction["method"],
                "p_error": None,
            },
        )
        logger.info(
            "Predicted severity for log %s using %s",
            row["log_id"],
            prediction["method"],
        )
        return True

    async def _predict(self, row: dict[str, Any]) -> dict[str, object]:
        log_id = row.get("log_id")
        organization_id = row.get("organization_id")
        message = row.get("message")
        service = row.get("service")
        if (
            not isinstance(log_id, str)
            or not isinstance(organization_id, str)
            or not isinstance(message, str)
            or not isinstance(service, str)
        ):
            raise ValueError("Queue record is missing required log fields")
        UUID(log_id)
        UUID(organization_id)

        source_severity = row.get("source_severity")
        if source_severity is not None and not isinstance(source_severity, str):
            raise ValueError("Queue record has an invalid source severity")

        recent_errors = row.get("recent_similar_errors")
        previous_errors = row.get("previous_similar_errors")
        criticality = row.get("service_criticality")
        if (
            isinstance(recent_errors, bool)
            or not isinstance(recent_errors, int)
            or isinstance(previous_errors, bool)
            or not isinstance(previous_errors, int)
            or recent_errors < 0
            or previous_errors < 0
        ):
            raise ValueError("Queue record has invalid error counts")
        if criticality not in {"low", "normal", "high", "critical"}:
            raise ValueError("Queue record has invalid service criticality")

        context = assess_severity_context(
            ContextSnapshot(
                recent_similar_errors=recent_errors,
                previous_similar_errors=previous_errors,
                template_seen_before=bool(row["template_seen_before"]),
                service_criticality=criticality,
                escalating_sequence=bool(row["escalating_sequence"]),
            )
        )
        rule_result = predict_severity_from_rules(message, source_severity)
        rule_decision = (
            LayerDecision(
                rule_result.severity,
                rule_result.confidence,
                rule_result.source,
                rule_result.reason,
            )
            if rule_result
            else None
        )
        nlp_result = (
            predict_with_nlp(self.classifier, message)
            if self.classifier is not None
            else None
        )
        nlp_decision = (
            LayerDecision(nlp_result.severity, nlp_result.confidence, "nlp")
            if nlp_result is not None
            else None
        )
        decisions = [
            decision
            for decision in (rule_decision, nlp_decision)
            if decision is not None
        ]

        if should_use_llm_fallback(decisions, context):
            llm_result = await predict_with_local_llm(
                message=message,
                service=service,
                source_severity=source_severity,
                rule_decision=rule_decision,
                nlp_decision=nlp_result,
                context=context,
                base_url=self.settings.ollama_url,
                model=self.settings.ollama_model,
            )
            return {
                "severity": llm_result.severity,
                "confidence": llm_result.confidence,
                "reason": llm_result.reason,
                "method": "local_llm",
            }

        if not decisions:
            raise RuntimeError("No severity layer produced a decision")

        selected = max(decisions, key=lambda decision: decision.confidence)
        if context.spike_detected and selected.severity in {"info", "debug", "trace"}:
            raise RuntimeError(
                "Context indicates an error spike but no higher-confidence "
                "severity decision is available"
            )
        return {
            "severity": selected.severity,
            "confidence": selected.confidence,
            "reason": selected.reason
            or f"Selected from the {selected.source} layer.",
            "method": selected.source,
        }

    async def _handle_prediction_error(
        self,
        row: dict[str, Any],
        error: Exception,
    ) -> None:
        message_id = row.get("message_id")
        log_id = row.get("log_id")
        read_count = row.get("read_count")
        if (
            isinstance(message_id, bool)
            or not isinstance(message_id, int)
            or not isinstance(log_id, str)
            or isinstance(read_count, bool)
            or not isinstance(read_count, int)
        ):
            raise RuntimeError("Queue claim metadata is invalid") from error

        if read_count < _MAX_LLM_ATTEMPTS:
            delay = min(2 ** read_count, 300)
            await self._rpc(
                "release_log_for_severity_retry",
                {
                    "p_message_id": message_id,
                    "p_delay_seconds": delay,
                },
            )
            logger.warning(
                "Prediction attempt %s for log %s failed (%s: %s); "
                "retrying in %s seconds",
                read_count,
                log_id,
                type(error).__name__,
                _safe_error_detail(error),
                delay,
            )
            return

        await self._rpc(
            "finish_log_severity_prediction",
            {
                "p_message_id": message_id,
                "p_log_id": log_id,
                "p_status": "failed",
                "p_severity": None,
                "p_confidence": None,
                "p_reason": None,
                "p_method": None,
                "p_error": f"Prediction failed after {_MAX_LLM_ATTEMPTS} attempts: "
                f"{type(error).__name__}: {_safe_error_detail(error)}",
            },
        )
        logger.error(
            "Prediction permanently failed for log %s after %s attempts (%s: %s)",
            log_id,
            _MAX_LLM_ATTEMPTS,
            type(error).__name__,
            _safe_error_detail(error),
        )


def _load_classifier() -> Pipeline | None:
    dataset_path = _PROJECT_ROOT / "data" / "severity_seed.jsonl"
    examples: list[LabeledExample] = load_approved_examples(dataset_path)
    try:
        classifier = train_severity_classifier(examples)
    except ValueError as error:
        logger.warning("NLP classifier unavailable: %s", error)
        return None
    logger.info("Loaded NLP classifier with %s approved examples", len(examples))
    return classifier


async def run_worker() -> None:
    settings = get_settings()
    if settings.severity_worker_poll_seconds <= 0:
        raise RuntimeError("SEVERITY_WORKER_POLL_SECONDS must be greater than zero")
    classifier = _load_classifier()
    async with httpx.AsyncClient(timeout=125.0) as client:
        worker = SeverityWorker(settings, classifier, client)
        logger.info("Severity worker started")
        while True:
            try:
                processed = await worker.process_one()
            except (httpx.HTTPError, RuntimeError, ValueError) as error:
                logger.error(
                    "Severity worker request failed (%s): %s",
                    type(error).__name__,
                    error,
                )
                await asyncio.sleep(settings.severity_worker_poll_seconds)
                continue
            if not processed:
                await asyncio.sleep(settings.severity_worker_poll_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
