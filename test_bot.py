"""Integration tests for PAL distribution bot — no Telegram/TON connectivity needed."""

import os
import sys
import tempfile
import json

from database import Database
from models import Proposal, Member, ReferenceValue
from social_matrix import extract_keywords, find_matching_categories, get_references, format_references, learn_from_proposal
from utils import validate_ton_address, format_pal_amount, format_status
from config import load_config
import messages

PASS = 0
FAIL = 0


def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name}")


def test_config():
    print("\n=== Config ===")
    config = load_config()
    check("config loads", isinstance(config, dict))
    check("has bot token key", "telegram_bot_token" in config)
    check("proposal_expiry_hours is float", isinstance(config["proposal_expiry_hours"], float))
    check("pal_decimals is int", isinstance(config["pal_decimals"], int))
    check("admin ids is list", isinstance(config["telegram_admin_user_ids"], list))


def test_utils():
    print("\n=== Utils ===")
    # Valid user-friendly addresses (EQ/UQ + 46 base64url chars)
    check("valid EQ address", validate_ton_address("EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2"))
    check("valid UQ address", validate_ton_address("UQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p0kD"))
    check("invalid address", not validate_ton_address("not_an_address"))
    check("invalid short", not validate_ton_address("EQabc"))
    # Raw format
    check("valid raw address", validate_ton_address("0:" + "a" * 64))
    check("invalid raw", not validate_ton_address("0:" + "g" * 64))

    check("format int amount", format_pal_amount(5.0) == "5")
    check("format float amount", format_pal_amount(5.25) == "5.25")
    check("format status IT", format_status("on_hold") == "In sospeso")
    check("format status approved", format_status("approved") == "Approvata")


def test_database():
    print("\n=== Database ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize()

        # Members
        db.upsert_member(123, "alice", "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2")
        member = db.get_member(123)
        check("member created", member is not None)
        check("member username", member.telegram_username == "alice")
        check("member address", "EQDtFpEwcFAEcRe5mLVh2N6C0" in member.ton_address)

        # Update member
        db.upsert_member(123, "alice_new", "UQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p0kD")
        member = db.get_member(123)
        check("member updated", member.telegram_username == "alice_new")

        db.upsert_member(456, "bob", "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2")

        # Proposals
        pid = db.create_proposal(
            proposer_user_id=123,
            event_name="Pulizia spiaggia Boccadasse",
            num_participants=10,
            pal_per_participant=1.0,
            pal_for_organiser=2.0,
            message_id=9999,
            chat_id=-100123,
        )
        check("proposal created", pid is not None and pid > 0)

        p = db.get_proposal(pid)
        check("proposal status awaiting", p.status == "awaiting_endorsement")
        check("proposal total", p.total_amount == 12.0)
        check("proposal event", p.event_name == "Pulizia spiaggia Boccadasse")
        check("proposal participants", p.num_participants == 10)

        # Endorse
        ok = db.endorse_proposal(pid, 456, 24.0)
        check("endorse success", ok)
        p = db.get_proposal(pid)
        check("status pending after endorse", p.status == "pending")
        check("endorser set", p.endorser_user_id == 456)
        check("expires_at set", p.expires_at is not None)

        # Cannot endorse twice
        ok2 = db.endorse_proposal(pid, 789, 24.0)
        check("cannot re-endorse", not ok2)

        # Object
        pid2 = db.create_proposal(123, "Test event", 5, 2.0, 3.0, 8888, -100123)
        db.endorse_proposal(pid2, 456, 24.0)
        ok = db.object_proposal(pid2, 789, "Troppi PAL richiesti")
        check("object success", ok)
        p2 = db.get_proposal(pid2)
        check("status on_hold", p2.status == "on_hold")
        check("objection reason", p2.objection_reason == "Troppi PAL richiesti")
        check("expires_at cleared", p2.expires_at is None)

        # Reinstate
        ok = db.reinstate_proposal(pid2, 24.0)
        check("reinstate success", ok)
        p2 = db.get_proposal(pid2)
        check("status pending after reinstate", p2.status == "pending")
        check("expires_at reset", p2.expires_at is not None)
        check("objection cleared", p2.objection_reason is None)

        # Reject
        pid3 = db.create_proposal(123, "Another event", 3, 1.0, 1.0, 7777, -100123)
        db.endorse_proposal(pid3, 456, 24.0)
        db.object_proposal(pid3, 789, "Non sono d'accordo")
        ok = db.reject_proposal(pid3)
        check("reject success", ok)
        p3 = db.get_proposal(pid3)
        check("status rejected", p3.status == "rejected")

        # Approve
        ok = db.approve_proposal(pid, "txhash123")
        check("approve success", ok)
        p = db.get_proposal(pid)
        check("status approved", p.status == "approved")
        check("tx_hash set", p.tx_hash == "txhash123")

        # Ledger
        db.insert_ledger_entry(pid, 12.0, "txhash123", "success")
        check("ledger entry created", True)  # no error = success

        # History
        history = db.get_recent_proposals(10)
        check("history has proposals", len(history) >= 3)

        user_props = db.get_user_proposals(123)
        check("user proposals", len(user_props) >= 3)

        # Seed values
        seed_file = os.path.join(os.path.dirname(__file__), "seed_values.json")
        db.load_seed_values(seed_file)
        refs = db.get_all_reference_values()
        check("seed values loaded", len(refs) == 9)

        # Don't reload seeds
        db.load_seed_values(seed_file)
        refs2 = db.get_all_reference_values()
        check("seeds not duplicated", len(refs2) == 9)

        # Search reference values
        results = db.search_reference_values(["cleanup", "pulizia"])
        check("search finds cleanup", len(results) > 0)

        # Search approved proposals
        past = db.search_approved_proposals(["pulizia", "spiaggia"])
        check("search finds approved", len(past) > 0)
        check("found correct proposal", past[0].event_name == "Pulizia spiaggia Boccadasse")


def test_social_matrix():
    print("\n=== Social Matrix ===")
    # Keyword extraction
    kw = extract_keywords("Pulizia della spiaggia a Boccadasse")
    check("keywords extracted", len(kw) > 0)
    check("stop words removed", "della" not in kw)
    check("pulizia in keywords", "pulizia" in kw)

    # Category matching
    cats = find_matching_categories(["pulizia", "spiaggia"])
    check("cleanup category found", "cleanup" in cats)

    cats2 = find_matching_categories(["laboratorio"])
    check("workshop category found", "workshop" in cats2)

    cats3 = find_matching_categories(["randomword"])
    check("no category for random", len(cats3) == 0)

    # References with DB
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize()
        seed_file = os.path.join(os.path.dirname(__file__), "seed_values.json")
        db.load_seed_values(seed_file)

        ref_vals, past_props = get_references(db, "Pulizia spiaggia Boccadasse")
        check("reference values found", len(ref_vals) > 0)

        formatted = format_references(ref_vals, past_props)
        check("formatted not empty", len(formatted) > 0)
        check("contains matrice sociale", "matrice sociale" in formatted)

        # No match
        ref_none, _ = get_references(db, "xyz abc 123")
        check("no refs for gibberish", len(ref_none) == 0)

        # Learn from proposal
        db.upsert_member(1, "test", "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2")
        pid = db.create_proposal(1, "Laboratorio di cucito", 8, 1.5, 3.0, 111, -100)
        db.endorse_proposal(pid, 1, 24)  # self-endorse just for test
        db.approve_proposal(pid, "tx123")
        proposal = db.get_proposal(pid)
        learn_from_proposal(db, proposal)
        refs = db.get_all_reference_values()
        learned = [r for r in refs if r.source == "learned"]
        check("learned value created", len(learned) > 0)
        check("learned has proposal_id", learned[0].proposal_id == pid)


def test_messages():
    print("\n=== Messages ===")
    check("help text", "/propose" in messages.help_text())
    check("help has matrix", "/matrix" in messages.help_text())

    p = Proposal(
        id=1, proposer_user_id=123, event_name="Test", num_participants=5,
        pal_per_participant=1.0, pal_for_organiser=2.0, total_amount=7.0,
        status="pending", created_at="2025-01-01T00:00:00",
    )
    summary = messages.propose_summary(p, "@alice")
    check("summary has event", "Test" in summary)
    check("summary has total", "7" in summary)
    check("summary has proposer", "@alice" in summary)

    status_text = messages.proposal_status(p)
    check("status has event", "Test" in status_text)

    row = messages.history_row(p)
    check("history row has id", "#1" in row)

    bal = messages.treasury_balance(100.5, 0.5)
    check("balance shows PAL", "100" in bal)

    obj = messages.objection_recorded(
        Proposal(id=1, proposer_user_id=123, event_name="X", num_participants=1,
                 pal_per_participant=1, pal_for_organiser=0, total_amount=1,
                 status="on_hold", created_at="", objection_reason="Too much"),
        "@bob"
    )
    check("objection shows reason", "Too much" in obj)
    check("objection shows IN SOSPESO", "IN SOSPESO" in obj)


def test_expired_proposals():
    print("\n=== Expired Proposal Queries ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize()

        db.upsert_member(1, "alice", "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2")
        db.upsert_member(2, "bob", "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2")

        # Create a proposal and endorse it with 0-hour expiry (already expired)
        pid = db.create_proposal(1, "Past event", 3, 1.0, 1.0, 111, -100)
        db.endorse_proposal(pid, 2, 0.0)  # expires immediately

        expired = db.get_expired_pending_proposals()
        check("finds expired proposal", len(expired) == 1)
        check("expired is correct id", expired[0].id == pid)

        # Create a proposal with long expiry
        pid2 = db.create_proposal(1, "Future event", 3, 1.0, 1.0, 222, -100)
        db.endorse_proposal(pid2, 2, 999.0)  # far future

        expired2 = db.get_expired_pending_proposals()
        check("future proposal not expired", len(expired2) == 1)  # still just the first one

        # Stale awaiting endorsement
        pid3 = db.create_proposal(1, "Stale event", 2, 1.0, 0.0, 333, -100)
        stale = db.get_stale_awaiting_proposals(0.0)  # 0 hours = everything is stale
        check("finds stale proposal", any(s.id == pid3 for s in stale))

        stale_none = db.get_stale_awaiting_proposals(9999.0)
        check("no stale with long window", not any(s.id == pid3 for s in stale_none))


if __name__ == "__main__":
    test_config()
    test_utils()
    test_database()
    test_social_matrix()
    test_messages()
    test_expired_proposals()

    print(f"\n{'=' * 50}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        sys.exit(1)
    else:
        print("All tests passed!")
