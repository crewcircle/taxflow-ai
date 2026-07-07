from dataclasses import dataclass


@dataclass
class LetterHandler:
    response_strategy: str
    evidence_checklist: list[str]
    timeline: str
    ato_reference_sections: list[str]
    response_template_type: str

    def get_strategy(self, classification: dict) -> dict:
        return {
            "response_strategy": self.response_strategy,
            "evidence_checklist": self.evidence_checklist,
            "timeline": self.timeline,
            "ato_reference_sections": self.ato_reference_sections,
            "response_template_type": self.response_template_type,
        }


HANDLER_REGISTRY: dict[str, LetterHandler] = {
    "bas_discrepancy": LetterHandler(
        response_strategy=(
            "Request a copy of the ATO's data matching information under s.353-15 TAA 1953. "
            "Review client's BAS workpapers. If discrepancy exists, lodge amended BAS. "
            "If ATO data is incorrect, prepare factual dispute response."
        ),
        evidence_checklist=[
            "Copy of lodged BAS",
            "Source documents for disputed amounts",
            "ATO data matching request response",
        ],
        timeline="Respond within 28 days. Request extension to 56 days if complex.",
        ato_reference_sections=["TAA 1953 s.353-15"],
        response_template_type="factual_dispute",
    ),
    "audit_initiation": LetterHandler(
        response_strategy="Acknowledge audit scope, gather requested records, request reasonable extension if needed.",
        evidence_checklist=["Audit notification letter", "Records requested by ATO", "Prior year workpapers"],
        timeline="Acknowledge within 14 days; provide records per ATO-specified deadline.",
        ato_reference_sections=["TAA 1953 Part 4-25"],
        response_template_type="audit_acknowledgement",
    ),
    "penalty_notice": LetterHandler(
        response_strategy="Assess penalty basis, consider remission request under PS LA 2011/19 if reasonable care taken.",
        evidence_checklist=["Penalty notice", "Circumstances leading to non-compliance", "Compliance history"],
        timeline="Respond within 28 days to preserve objection rights.",
        ato_reference_sections=["TAA 1953 s.284-75", "PS LA 2011/19"],
        response_template_type="remission_request",
    ),
    "garnishee_notice": LetterHandler(
        response_strategy="Contact ATO debt line immediately, negotiate payment plan to have garnishee lifted.",
        evidence_checklist=["Garnishee notice", "Cash flow statement", "Proposed payment plan"],
        timeline="Urgent - respond within 48 hours.",
        ato_reference_sections=["TAA 1953 s.260-5"],
        response_template_type="payment_arrangement",
    ),
    "position_paper": LetterHandler(
        response_strategy="Review ATO's technical position, prepare a formal rebuttal citing contrary authority where available.",
        evidence_checklist=["Position paper", "Supporting technical authorities", "Client facts"],
        timeline="Respond within timeframe stated in position paper (typically 28 days).",
        ato_reference_sections=["TAA 1953 Part IVC"],
        response_template_type="technical_rebuttal",
    ),
    "objection_result": LetterHandler(
        response_strategy="If unfavourable, consider AAT/Federal Court appeal within 60 days; else close matter.",
        evidence_checklist=["Objection decision letter", "Original objection", "Advice on merits of appeal"],
        timeline="60 days to lodge an appeal with the AAT.",
        ato_reference_sections=["TAA 1953 Part IVC"],
        response_template_type="appeal_advice",
    ),
    "ato_debt_notice": LetterHandler(
        response_strategy="Verify debt accuracy, negotiate payment plan or dispute if incorrect.",
        evidence_checklist=["Debt notice", "Payment history", "Statement of account"],
        timeline="Respond within 14 days to avoid escalation.",
        ato_reference_sections=["TAA 1953 s.255-5"],
        response_template_type="payment_arrangement",
    ),
    "payment_plan_request": LetterHandler(
        response_strategy="Prepare a realistic payment proposal supported by cash flow forecast.",
        evidence_checklist=["Cash flow forecast", "Proposed instalment schedule"],
        timeline="Respond within 14 days.",
        ato_reference_sections=["TAA 1953 s.255-15"],
        response_template_type="payment_arrangement",
    ),
    "lodgement_reminder": LetterHandler(
        response_strategy="Lodge outstanding return/statement immediately, or request deferral with reason.",
        evidence_checklist=["Outstanding return details", "Reason for delay"],
        timeline="Lodge within 14 days.",
        ato_reference_sections=["TAA 1953 s.286-75"],
        response_template_type="lodgement_confirmation",
    ),
    "audit_completion": LetterHandler(
        response_strategy="Review amended assessment, consider objection if amount or basis is disputed.",
        evidence_checklist=["Amended assessment", "Audit findings", "Supporting facts"],
        timeline="60 days to lodge an objection.",
        ato_reference_sections=["TAA 1953 s.170", "Part IVC"],
        response_template_type="objection_letter",
    ),
    "abn_cancellation": LetterHandler(
        response_strategy="Demonstrate ongoing enterprise activity to prevent cancellation.",
        evidence_checklist=["Evidence of trading activity", "Recent invoices/contracts"],
        timeline="Respond within 28 days.",
        ato_reference_sections=["A New Tax System (ABN) Act 1999 s.9"],
        response_template_type="factual_dispute",
    ),
    "gst_registration": LetterHandler(
        response_strategy="Confirm turnover position and registration status with supporting records.",
        evidence_checklist=["Turnover calculations", "GST registration history"],
        timeline="Respond within 28 days.",
        ato_reference_sections=["GST Act s.23-5"],
        response_template_type="factual_dispute",
    ),
    "employer_obligations": LetterHandler(
        response_strategy="Review PAYG/SG compliance, lodge any outstanding SG charge statements.",
        evidence_checklist=["Payroll records", "SG contribution history", "Employee classification analysis"],
        timeline="Respond within 28 days.",
        ato_reference_sections=["SGA Act s.33", "TAA 1953"],
        response_template_type="compliance_review",
    ),
    "lifestyle_assets": LetterHandler(
        response_strategy="Reconcile asset acquisition with reported income; explain funding source.",
        evidence_checklist=["Asset purchase records", "Funding source evidence", "Loan agreements if applicable"],
        timeline="Respond within 28 days.",
        ato_reference_sections=["ITAA 1997 s.6-5"],
        response_template_type="factual_dispute",
    ),
    "taxable_payments": LetterHandler(
        response_strategy="Reconcile TPAR data with contractor payment records, lodge amendment if needed.",
        evidence_checklist=["TPAR lodged", "Contractor payment records"],
        timeline="Respond within 28 days.",
        ato_reference_sections=["TAA 1953 Sch 1 s.396-55"],
        response_template_type="factual_dispute",
    ),
}


def get_handler(letter_type: str) -> LetterHandler:
    return HANDLER_REGISTRY[letter_type]
