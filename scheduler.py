"""Background scheduler for auto-approving proposals and cleaning up stale ones."""

import logging
from telegram.ext import CallbackContext

import messages
from social_matrix import learn_from_proposal

logger = logging.getLogger(__name__)


async def check_expired_proposals(context: CallbackContext):
    """Scheduled job: auto-approve pending proposals past their 24h window."""
    db = context.bot_data["db"]
    jetton = context.bot_data.get("jetton")
    config = context.bot_data["config"]

    # --- Auto-approve expired pending proposals ---
    expired = db.get_expired_pending_proposals()
    for proposal in expired:
        try:
            if proposal.proposal_type == 'incentive':
                await _approve_incentive(context, db, proposal)
            else:
                await _approve_pal(context, db, jetton, proposal)
        except Exception as e:
            logger.error(f"Failed to auto-approve proposal {proposal.id}: {e}")
            db.fail_proposal(proposal.id)
            await _notify_failure(context, proposal, str(e))

    # --- Expire stale awaiting_endorsement proposals ---
    stale = db.get_stale_awaiting_proposals(config["endorsement_expiry_hours"])
    for proposal in stale:
        db.expire_proposal(proposal.id)
        try:
            await context.bot.send_message(
                chat_id=proposal.chat_id,
                text=messages.endorsement_expired(proposal.id),
            )
            # Remove inline buttons from the original message
            await context.bot.edit_message_reply_markup(
                chat_id=proposal.chat_id,
                message_id=proposal.message_id,
                reply_markup=None,
            )
        except Exception as e:
            logger.warning(f"Could not notify about expired proposal {proposal.id}: {e}")
        logger.info(f"Proposal {proposal.id} expired (no endorsement)")


async def _approve_incentive(context: CallbackContext, db, proposal):
    """Auto-approve an incentive proposal: create the incentive record, no PAL transfer."""
    incentive_id = db.create_incentive(
        description=proposal.incentive_description or proposal.event_name,
        offered_by=proposal.incentive_offered_by or "",
        conditions=proposal.incentive_conditions or "",
        proposal_id=proposal.id,
    )
    db.approve_proposal(proposal.id)
    incentive = db.get_incentive(incentive_id)
    notification = messages.auto_approved_incentive(proposal, incentive)
    try:
        await context.bot.edit_message_text(
            chat_id=proposal.chat_id,
            message_id=proposal.message_id,
            text=notification,
        )
    except Exception as e:
        logger.warning(f"Could not edit message for incentive proposal {proposal.id}: {e}")
    await context.bot.send_message(chat_id=proposal.chat_id, text=notification)
    logger.info(f"Incentive proposal {proposal.id} auto-approved, incentive #{incentive_id}")


async def _approve_pal(context: CallbackContext, db, jetton, proposal):
    """Auto-approve a PAL distribution proposal: transfer Jetton tokens."""
    member = db.get_member(proposal.proposer_user_id)
    if not member or not member.ton_address:
        logger.error(f"Proposal {proposal.id}: proposer has no registered wallet")
        db.fail_proposal(proposal.id)
        await _notify_failure(context, proposal, "Il proponente non ha un wallet registrato.")
        return

    if not jetton:
        logger.error(f"Proposal {proposal.id}: Jetton module not configured")
        db.fail_proposal(proposal.id)
        await _notify_failure(context, proposal, "Modulo Jetton non configurato.")
        return

    pal_balance = await jetton.get_pal_balance()
    if pal_balance < proposal.total_amount:
        logger.error(
            f"Proposal {proposal.id}: insufficient PAL "
            f"(need {proposal.total_amount}, have {pal_balance})"
        )
        db.fail_proposal(proposal.id)
        await _notify_failure(
            context, proposal,
            f"Saldo PAL insufficiente ({pal_balance:.2f} disponibili, "
            f"{proposal.total_amount:.2f} richiesti)."
        )
        return

    tx_hash = await jetton.send_pal_tokens(member.ton_address, proposal.total_amount)
    success = db.approve_proposal(proposal.id, tx_hash)
    if success:
        db.insert_ledger_entry(proposal.id, proposal.total_amount, tx_hash, "success")
        updated_proposal = db.get_proposal(proposal.id)
        learn_from_proposal(db, updated_proposal)
        await _edit_approved(context, proposal, tx_hash)
        await context.bot.send_message(
            chat_id=proposal.chat_id,
            text=messages.auto_approved(proposal, tx_hash),
        )
        logger.info(f"Proposal {proposal.id} auto-approved, tx: {tx_hash}")


async def _edit_approved(context: CallbackContext, proposal, tx_hash: str):
    """Edit the original proposal message to show approved status."""
    try:
        await context.bot.edit_message_text(
            chat_id=proposal.chat_id,
            message_id=proposal.message_id,
            text=messages.auto_approved(proposal, tx_hash),
        )
    except Exception as e:
        logger.warning(f"Could not edit message for approved proposal {proposal.id}: {e}")


async def _notify_failure(context: CallbackContext, proposal, error_msg: str):
    """Notify group about a failed auto-approval."""
    try:
        await context.bot.send_message(
            chat_id=proposal.chat_id,
            text=messages.auto_approval_failed(proposal, error_msg),
        )
    except Exception as e:
        logger.warning(f"Could not notify about failed proposal {proposal.id}: {e}")
