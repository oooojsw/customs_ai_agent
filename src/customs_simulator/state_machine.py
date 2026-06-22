from __future__ import annotations

from .models import CustomsStage


TRANSITIONS: dict[CustomsStage, set[CustomsStage]] = {
    CustomsStage.DRAFT: {CustomsStage.DOCUMENTS_READY, CustomsStage.CANCELLED},
    CustomsStage.DOCUMENTS_READY: {
        CustomsStage.PRECHECK_PASSED,
        CustomsStage.CANCELLED,
    },
    CustomsStage.PRECHECK_PASSED: {
        CustomsStage.READY_TO_SUBMIT,
        CustomsStage.CANCELLED,
    },
    CustomsStage.READY_TO_SUBMIT: {
        CustomsStage.SUBMITTED,
        CustomsStage.CANCELLED,
    },
    CustomsStage.SUBMITTED: {
        CustomsStage.ACCEPTED,
        CustomsStage.RETURNED,
        CustomsStage.SUPPLEMENT_REQUIRED,
        CustomsStage.REJECTED,
    },
    CustomsStage.SUPPLEMENT_REQUIRED: {
        CustomsStage.SUBMITTED,
        CustomsStage.REJECTED,
        CustomsStage.CANCELLED,
    },
    CustomsStage.RETURNED: {
        CustomsStage.READY_TO_SUBMIT,
        CustomsStage.CANCELLED,
    },
    CustomsStage.ACCEPTED: {CustomsStage.UNDER_REVIEW},
    CustomsStage.UNDER_REVIEW: {
        CustomsStage.PRICE_QUERY,
        CustomsStage.LICENSE_REVIEW,
        CustomsStage.INSPECTION_REQUIRED,
        CustomsStage.TAX_ASSESSED,
        CustomsStage.REJECTED,
    },
    CustomsStage.PRICE_QUERY: {
        CustomsStage.UNDER_REVIEW,
        CustomsStage.INSPECTION_REQUIRED,
        CustomsStage.REJECTED,
    },
    CustomsStage.LICENSE_REVIEW: {
        CustomsStage.UNDER_REVIEW,
        CustomsStage.REJECTED,
    },
    CustomsStage.INSPECTION_REQUIRED: {
        CustomsStage.INSPECTION_SCHEDULED,
        CustomsStage.CANCELLED,
    },
    CustomsStage.INSPECTION_SCHEDULED: {
        CustomsStage.INSPECTION_COMPLETED,
    },
    CustomsStage.INSPECTION_COMPLETED: {
        CustomsStage.TAX_ASSESSED,
        CustomsStage.REJECTED,
    },
    CustomsStage.TAX_ASSESSED: {CustomsStage.PAYMENT_PENDING},
    CustomsStage.PAYMENT_PENDING: {
        CustomsStage.TAX_PAID,
        CustomsStage.CANCELLED,
    },
    CustomsStage.TAX_PAID: {CustomsStage.RELEASED},
    CustomsStage.RELEASED: {CustomsStage.PICKED_UP},
    CustomsStage.PICKED_UP: {CustomsStage.CLOSED},
}

for _stage in CustomsStage:
    if _stage not in {
        CustomsStage.CLOSED,
        CustomsStage.REJECTED,
        CustomsStage.CANCELLED,
    }:
        TRANSITIONS.setdefault(_stage, set()).add(CustomsStage.CANCELLED)


class InvalidStateTransition(ValueError):
    pass


def ensure_transition(current: CustomsStage, target: CustomsStage) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise InvalidStateTransition(
            f"INVALID_CUSTOMS_STATE_TRANSITION: {current.value} -> {target.value}"
        )


def allowed_actions(stage: CustomsStage) -> list[str]:
    mapping = {
        CustomsStage.DRAFT: ["LOAD_DOCUMENTS", "CANCEL"],
        CustomsStage.DOCUMENTS_READY: ["RUN_PRECHECK", "CANCEL"],
        CustomsStage.PRECHECK_PASSED: ["BUILD_DECLARATION", "CANCEL"],
        CustomsStage.READY_TO_SUBMIT: ["SUBMIT_DECLARATION", "CANCEL"],
        CustomsStage.SUBMITTED: ["PROCESS_ACCEPTANCE"],
        CustomsStage.RETURNED: ["AMEND_DECLARATION", "CANCEL"],
        CustomsStage.SUPPLEMENT_REQUIRED: [
            "SUBMIT_SUPPLEMENT",
            "CANCEL",
        ],
        CustomsStage.ACCEPTED: ["START_REVIEW"],
        CustomsStage.UNDER_REVIEW: ["PROCESS_REVIEW"],
        CustomsStage.PRICE_QUERY: ["RESPOND_PRICE_QUERY"],
        CustomsStage.LICENSE_REVIEW: ["CONFIRM_LICENSE"],
        CustomsStage.INSPECTION_REQUIRED: ["SCHEDULE_INSPECTION"],
        CustomsStage.INSPECTION_SCHEDULED: ["COMPLETE_INSPECTION"],
        CustomsStage.INSPECTION_COMPLETED: ["ASSESS_TAX"],
        CustomsStage.TAX_ASSESSED: ["ISSUE_TAX_BILL"],
        CustomsStage.PAYMENT_PENDING: ["PAY_TAX", "CANCEL"],
        CustomsStage.TAX_PAID: ["RELEASE"],
        CustomsStage.RELEASED: ["PICK_UP"],
        CustomsStage.PICKED_UP: ["CLOSE_CASE"],
    }
    actions = list(mapping.get(stage, []))
    if (
        stage
        not in {
            CustomsStage.CLOSED,
            CustomsStage.REJECTED,
            CustomsStage.CANCELLED,
        }
        and "CANCEL" not in actions
    ):
        actions.append("CANCEL")
    return actions
