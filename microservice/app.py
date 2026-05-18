#!/usr/bin/env python3
"""
Email Approval Microservice

Polls an IMAP mailbox on a configurable interval. When it finds an unread
email matching the subject filter whose body contains the approval keyword,
it calls the AAP REST API to approve the pending workflow approval node.

The approval node ID is embedded in the email body by the AAP playbook as:
  Approval Reference: WFJ-<workflow_job_id>/<approval_node_id>

If no specific ID is found, all pending approvals are approved.

Configuration is provided entirely through environment variables (injected
from the OCP Secret `email-approver-secret`).
"""

import email
import imaplib
import logging
import os
import re
import time

import requests

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
IMAP_HOST        = os.environ["IMAP_HOST"]
IMAP_PORT        = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER        = os.environ["IMAP_USER"]
IMAP_PASS        = os.environ["IMAP_PASS"]

AAP_BASE_URL     = os.environ["AAP_BASE_URL"]
AAP_TOKEN        = os.environ["AAP_TOKEN"]
AAP_VERIFY       = os.environ.get("AAP_VERIFY_SSL", "false").lower() == "true"

APPROVAL_KEYWORD = os.environ.get("APPROVAL_KEYWORD", "approved").lower()
SUBJECT_FILTER   = os.environ.get("SUBJECT_FILTER", "[GitOps APPROVAL REQUIRED]")
POLL_INTERVAL    = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))


# ── AAP API helpers ──────────────────────────────────────────────────────────

def _aap_headers() -> dict:
    return {
        "Authorization": f"Bearer {AAP_TOKEN}",
        "Content-Type": "application/json",
    }


def get_pending_approvals() -> dict:
    """Return {str(id): approval_object} for all pending workflow approvals."""
    try:
        r = requests.get(
            f"{AAP_BASE_URL}/api/v2/workflow_approvals/",
            params={"status": "pending"},
            headers=_aap_headers(),
            verify=AAP_VERIFY,
            timeout=15,
        )
        r.raise_for_status()
        return {str(item["id"]): item for item in r.json().get("results", [])}
    except Exception as exc:
        log.error("Failed to list pending approvals: %s", exc)
        return {}


def call_approve(approval_id: str) -> bool:
    """POST to the AAP approve endpoint for a given approval node ID."""
    try:
        r = requests.post(
            f"{AAP_BASE_URL}/api/v2/workflow_approvals/{approval_id}/approve/",
            headers=_aap_headers(),
            json={},
            verify=AAP_VERIFY,
            timeout=15,
        )
        r.raise_for_status()
        log.info("Approved workflow_approval id=%s  (HTTP %s)", approval_id, r.status_code)
        return True
    except Exception as exc:
        log.error("Approve call failed for id=%s: %s", approval_id, exc)
        return False


# ── Email helpers ─────────────────────────────────────────────────────────────

def extract_text(msg: email.message.Message) -> str:
    """Extract the plain-text body from an email.Message object."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""


# ── Core loop ─────────────────────────────────────────────────────────────────

def process_inbox() -> None:
    """Connect to IMAP, find approval emails, and trigger AAP approvals."""
    pending = get_pending_approvals()
    log.info("Pending approvals: %d", len(pending))
    if not pending:
        return

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
        imap.login(IMAP_USER, IMAP_PASS)
        imap.select("INBOX")

        _, nums = imap.search(None, f'(UNSEEN SUBJECT "{SUBJECT_FILTER}")')
        msg_ids = nums[0].split()
        log.info("Unread matching emails found: %d", len(msg_ids))

        for mid in msg_ids:
            _, data = imap.fetch(mid, "(RFC822)")
            msg  = email.message_from_bytes(data[0][1])
            body = extract_text(msg)

            log.info(
                "Processing email — From: %s | Subject: %s",
                msg.get("From", "?"),
                msg.get("Subject", "?"),
            )

            if APPROVAL_KEYWORD not in body.lower():
                log.info("Approval keyword not found in body — skipping")
                imap.store(mid, "+FLAGS", "\\Seen")
                continue

            match = re.search(r"WFJ-\d+/(\d+)", body)
            if match:
                appr_id = match.group(1)
                log.info("Found embedded approval ID: %s", appr_id)
                if appr_id in pending:
                    if call_approve(appr_id):
                        imap.store(mid, "+FLAGS", "\\Seen")
                else:
                    log.warning("Approval ID %s not in current pending list; trying anyway", appr_id)
                    if call_approve(appr_id):
                        imap.store(mid, "+FLAGS", "\\Seen")
            else:
                log.info("No specific ID found; approving all %d pending approvals", len(pending))
                for appr_id in list(pending.keys()):
                    call_approve(appr_id)
                imap.store(mid, "+FLAGS", "\\Seen")


def main() -> None:
    log.info(
        "Email Approval Microservice starting  |  IMAP: %s@%s  |  AAP: %s  |  Poll: %ds",
        IMAP_USER, IMAP_HOST, AAP_BASE_URL, POLL_INTERVAL,
    )
    while True:
        try:
            process_inbox()
        except Exception as exc:
            log.error("Unhandled error in main loop: %s", exc, exc_info=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
