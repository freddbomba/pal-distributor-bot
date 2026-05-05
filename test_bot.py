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


def test_incentives():
    print("\n=== Incentives ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize()

        db.upsert_member(1, "alice", "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2")
        db.upsert_member(2, "bob", "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2")

        # Incentive proposal creation
        pid = db.create_proposal(
            proposer_user_id=1,
            event_name="[Incentivo] 5% di sconto in PAL",
            num_participants=0,
            pal_per_participant=0.0,
            pal_for_organiser=0.0,
            message_id=1111,
            chat_id=-100,
            proposal_type="incentive",
            incentive_offered_by="Bottega del Pane",
            incentive_description="5% di sconto pagando in PAL",
            incentive_conditions="Acquisti superiori a 5 PAL",
        )
        check("incentive proposal created", pid is not None and pid > 0)

        p = db.get_proposal(pid)
        check("proposal_type is incentive", p.proposal_type == "incentive")
        check("incentive_offered_by set", p.incentive_offered_by == "Bottega del Pane")
        check("incentive_description set", p.incentive_description == "5% di sconto pagando in PAL")
        check("incentive_conditions set", p.incentive_conditions == "Acquisti superiori a 5 PAL")
        check("total_amount is 0", p.total_amount == 0.0)

        # PAL proposal still defaults correctly
        pid_pal = db.create_proposal(1, "Evento test", 5, 2.0, 1.0, 2222, -100)
        p_pal = db.get_proposal(pid_pal)
        check("pal proposal type default", p_pal.proposal_type == "pal_distribution")
        check("pal proposal no incentive fields", p_pal.incentive_offered_by is None)

        # Approve incentive proposal and create incentive record
        db.endorse_proposal(pid, 2, 24.0)
        db.approve_proposal(pid)
        inc_id = db.create_incentive(
            description=p.incentive_description,
            offered_by=p.incentive_offered_by,
            conditions=p.incentive_conditions,
            proposal_id=pid,
        )
        check("incentive record created", inc_id is not None and inc_id > 0)

        inc = db.get_incentive(inc_id)
        check("incentive get works", inc is not None)
        check("incentive description", inc.description == "5% di sconto pagando in PAL")
        check("incentive offered_by", inc.offered_by == "Bottega del Pane")
        check("incentive conditions", inc.conditions == "Acquisti superiori a 5 PAL")
        check("incentive status active", inc.status == "active")
        check("incentive proposal_id", inc.proposal_id == pid)

        # Active incentives listing
        active = db.get_active_incentives()
        check("active incentives has one", len(active) == 1)
        check("active incentive id matches", active[0].id == inc_id)

        # Expiration
        ok = db.expire_incentive(inc_id)
        check("expire returns true", ok)
        inc_after = db.get_incentive(inc_id)
        check("incentive now expired", inc_after.status == "expired")
        active_after = db.get_active_incentives()
        check("no active incentives after expire", len(active_after) == 0)
        ok2 = db.expire_incentive(inc_id)
        check("cannot expire twice", not ok2)

        # Messages
        from models import Incentive
        fake_inc = Incentive(
            id=1, description="Sconto 10%", offered_by="Negozio Test",
            conditions="Min 10 PAL", status="active", created_at="2025-01-01"
        )
        listing = messages.incentives_list([fake_inc])
        check("incentives list shows offered_by", "Negozio Test" in listing)
        check("incentives list shows description", "Sconto 10%" in listing)
        check("incentives list shows conditions", "Min 10 PAL" in listing)

        empty_listing = messages.incentives_list([])
        check("empty incentives message", "Nessun incentivo" in empty_listing)

        # propose_incentive_summary
        proposal_for_msg = db.get_proposal(pid)
        summary = messages.propose_incentive_summary(proposal_for_msg, "@alice")
        check("incentive summary has offered_by", "Bottega del Pane" in summary)
        check("incentive summary has description", "5% di sconto" in summary)
        check("incentive summary has proposer", "@alice" in summary)

        # auto_approved_incentive
        approved_msg = messages.auto_approved_incentive(proposal_for_msg, fake_inc)
        check("auto_approved_incentive has ATTIVATO", "ATTIVATO" in approved_msg)
        check("auto_approved_incentive has offered_by", "Negozio Test" in approved_msg)
        check("auto_approved_incentive references proposal", str(pid) in approved_msg)

        # Help text includes new commands
        check("help has propose_incentive", "/propose_incentive" in messages.help_text())
        check("help has incentives", "/incentives" in messages.help_text())
        check("help has expire_incentive", "/expire_incentive" in messages.help_text())


def test_confirm_flow():
    print("\n=== Confirm / Abort Flow ===")

    # propose_confirm_summary formatting
    text = messages.propose_confirm_summary("Sagra del Pesto", 12, 2.5, 5.0, 35.0)
    check("confirm summary has event", "Sagra del Pesto" in text)
    check("confirm summary has participants", "12" in text)
    check("confirm summary has total", "35" in text)
    check("confirm summary has PAL per partecipante", "2.5" in text)
    check("confirm summary has PAL organizzatore", "5" in text)
    check("confirm summary asks Confermi", "Confermi" in text)

    # incentive_confirm_summary formatting
    itext = messages.incentive_confirm_summary(
        "Bottega Verde", "10% sconto in PAL", "Minimo 5 PAL"
    )
    check("incentive confirm has offered_by", "Bottega Verde" in itext)
    check("incentive confirm has description", "10% sconto" in itext)
    check("incentive confirm has conditions", "Minimo 5 PAL" in itext)
    check("incentive confirm asks Confermi", "Confermi" in itext)

    # Abort path: no proposal created in DB
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize()
        db.upsert_member(1, "alice", "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2")

        # Simulate abort: no create_proposal called — DB should be empty
        proposals_before = db.get_recent_proposals(10)
        check("no proposals before confirm", len(proposals_before) == 0)

        # Simulate confirm: create_proposal is called exactly once
        pid = db.create_proposal(1, "Sagra del Pesto", 12, 2.5, 5.0, 999, -100)
        proposals_after = db.get_recent_proposals(10)
        check("one proposal after confirm", len(proposals_after) == 1)
        check("proposal has correct event", proposals_after[0].event_name == "Sagra del Pesto")

    # ConversationHandler states include CONFIRM
    from conversation import build_conversation_handler, CONFIRM as PAL_CONFIRM
    from conversation_incentive import build_incentive_conversation_handler, CONFIRM as INC_CONFIRM

    pal_handler = build_conversation_handler(300)
    check("PAL handler has CONFIRM state", PAL_CONFIRM in pal_handler.states)
    check("PAL CONFIRM has two callbacks", len(pal_handler.states[PAL_CONFIRM]) == 2)

    inc_handler = build_incentive_conversation_handler(300)
    check("incentive handler has CONFIRM state", INC_CONFIRM in inc_handler.states)
    check("incentive CONFIRM has two callbacks", len(inc_handler.states[INC_CONFIRM]) == 2)


if __name__ == "__main__":
    test_config()
    test_utils()
    test_database()
    test_social_matrix()
    test_messages()
    test_expired_proposals()
    test_incentives()
    test_confirm_flow()

    print(f"\n{'=' * 50}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        sys.exit(1)
    else:
        print("All tests passed!")
