"""Telegram command and callback handlers for the PAL distribution bot."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

import messages
from utils import validate_ton_address, format_pal_amount

logger = logging.getLogger(__name__)


def _is_admin(user_id: int, config: dict) -> bool:
    return user_id in config["telegram_admin_user_ids"]


def _user_display_name(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name


# --- /register ---

async def register_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]
    user = update.effective_user

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Uso: /register <indirizzo_TON>")
        return

    address = context.args[0].strip()
    if not validate_ton_address(address):
        await update.message.reply_text(messages.invalid_ton_address())
        return

    existing = db.get_member(user.id)
    db.upsert_member(user.id, user.username, address)

    if existing:
        await update.message.reply_text(messages.registration_updated(address))
    else:
        await update.message.reply_text(messages.registration_success(address))


# --- /endorse (command) ---

async def endorse_command_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = update.effective_user

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Uso: /endorse <id_proposta>")
        return

    try:
        proposal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID proposta non valido.")
        return

    await _do_endorse(update, context, db, config, user, proposal_id)


async def endorse_callback_handler(update: Update, context: CallbackContext):
    """Handle inline button callback for endorsing."""
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = query.from_user

    proposal_id = int(query.data.split(":")[1])
    await _do_endorse(update, context, db, config, user, proposal_id, is_callback=True)


async def _do_endorse(update, context, db, config, user, proposal_id, is_callback=False):
    proposal = db.get_proposal(proposal_id)
    if not proposal:
        text = messages.proposal_not_found(proposal_id)
        if is_callback:
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return

    if proposal.status != "awaiting_endorsement":
        text = messages.already_endorsed()
        if is_callback:
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return

    if user.id == proposal.proposer_user_id:
        text = messages.cannot_endorse_own()
        if is_callback:
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return

    success = db.endorse_proposal(proposal_id, user.id, config["proposal_expiry_hours"])
    if not success:
        return

    # Refresh proposal from DB
    proposal = db.get_proposal(proposal_id)
    endorser_name = _user_display_name(user)

    # Get proposer name
    proposer_member = db.get_member(proposal.proposer_user_id)
    proposer_name = f"@{proposer_member.telegram_username}" if proposer_member and proposer_member.telegram_username else f"User {proposal.proposer_user_id}"

    # Edit original message to show endorsed status with Object button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Obietta / Object", callback_data=f"object:{proposal_id}")]
    ])
    try:
        await context.bot.edit_message_text(
            chat_id=proposal.chat_id,
            message_id=proposal.message_id,
            text=messages.proposal_endorsed_update(proposal, proposer_name, endorser_name),
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.warning(f"Could not edit message for proposal {proposal_id}: {e}")

    # Send notification
    chat_id = update.callback_query.message.chat_id if is_callback else update.message.chat_id
    await context.bot.send_message(
        chat_id=chat_id,
        text=messages.endorsed(proposal, endorser_name),
    )


# --- /object (command) ---

async def object_command_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]
    user = update.effective_user

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(messages.objection_reason_required())
        return

    try:
        proposal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID proposta non valido.")
        return

    reason = " ".join(context.args[1:])
    await _do_object(update, context, db, user, proposal_id, reason)


async def object_callback_handler(update: Update, context: CallbackContext):
    """Handle inline button callback for objecting. Prompts for reason."""
    query = update.callback_query
    await query.answer()

    proposal_id = int(query.data.split(":")[1])

    # Store pending objection state — user must reply with reason
    context.user_data["pending_objection_proposal_id"] = proposal_id
    await query.message.reply_text(
        messages.object_prompt_reason()
        + f"\n\n(Proposta #{proposal_id} — rispondi con /object {proposal_id} <motivo>)"
    )


async def _do_object(update, context, db, user, proposal_id, reason):
    proposal = db.get_proposal(proposal_id)
    if not proposal:
        await update.message.reply_text(messages.proposal_not_found(proposal_id))
        return

    if proposal.status != "pending":
        await update.message.reply_text(
            messages.wrong_status(proposal_id, "pending", proposal.status)
        )
        return

    if user.id == proposal.proposer_user_id:
        await update.message.reply_text(messages.cannot_object_own())
        return

    if not reason.strip():
        await update.message.reply_text(messages.objection_reason_required())
        return

    success = db.object_proposal(proposal_id, user.id, reason)
    if not success:
        return

    # Refresh proposal
    proposal = db.get_proposal(proposal_id)
    objector_name = _user_display_name(user)

    # Get proposer name
    proposer_member = db.get_member(proposal.proposer_user_id)
    proposer_name = f"@{proposer_member.telegram_username}" if proposer_member and proposer_member.telegram_username else f"User {proposal.proposer_user_id}"

    # Edit original message to show on_hold status
    try:
        await context.bot.edit_message_text(
            chat_id=proposal.chat_id,
            message_id=proposal.message_id,
            text=messages.proposal_on_hold_update(proposal, proposer_name, objector_name),
        )
    except Exception as e:
        logger.warning(f"Could not edit message for proposal {proposal_id}: {e}")

    # Send notification
    await update.message.reply_text(messages.objection_recorded(proposal, objector_name))


# --- /reinstate (admin) ---

async def reinstate_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = update.effective_user

    if not _is_admin(user.id, config):
        await update.message.reply_text(messages.admin_only())
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Uso: /reinstate <id_proposta>")
        return

    try:
        proposal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID proposta non valido.")
        return

    proposal = db.get_proposal(proposal_id)
    if not proposal:
        await update.message.reply_text(messages.proposal_not_found(proposal_id))
        return

    if proposal.status != "on_hold":
        await update.message.reply_text(
            messages.wrong_status(proposal_id, "on_hold", proposal.status)
        )
        return

    success = db.reinstate_proposal(proposal_id, config["proposal_expiry_hours"])
    if not success:
        return

    # Refresh proposal and update message
    proposal = db.get_proposal(proposal_id)
    proposer_member = db.get_member(proposal.proposer_user_id)
    proposer_name = f"@{proposer_member.telegram_username}" if proposer_member and proposer_member.telegram_username else f"User {proposal.proposer_user_id}"
    endorser_name = ""
    if proposal.endorser_user_id:
        endorser_member = db.get_member(proposal.endorser_user_id)
        endorser_name = f"@{endorser_member.telegram_username}" if endorser_member and endorser_member.telegram_username else f"User {proposal.endorser_user_id}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Obietta / Object", callback_data=f"object:{proposal_id}")]
    ])
    try:
        await context.bot.edit_message_text(
            chat_id=proposal.chat_id,
            message_id=proposal.message_id,
            text=messages.proposal_endorsed_update(proposal, proposer_name, endorser_name),
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.warning(f"Could not edit message for proposal {proposal_id}: {e}")

    await update.message.reply_text(messages.reinstated(proposal_id))


# --- /reject (admin) ---

async def reject_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = update.effective_user

    if not _is_admin(user.id, config):
        await update.message.reply_text(messages.admin_only())
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Uso: /reject <id_proposta>")
        return

    try:
        proposal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID proposta non valido.")
        return

    proposal = db.get_proposal(proposal_id)
    if not proposal:
        await update.message.reply_text(messages.proposal_not_found(proposal_id))
        return

    if proposal.status != "on_hold":
        await update.message.reply_text(
            messages.wrong_status(proposal_id, "on_hold", proposal.status)
        )
        return

    success = db.reject_proposal(proposal_id)
    if success:
        await update.message.reply_text(messages.rejected(proposal_id))


# --- /history ---

async def history_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]

    limit = 10
    if context.args:
        try:
            limit = int(context.args[0])
            limit = max(1, min(limit, 50))
        except ValueError:
            pass

    proposals = db.get_recent_proposals(limit)
    if not proposals:
        await update.message.reply_text(messages.no_proposals())
        return

    lines = [messages.history_header(len(proposals))]
    for p in proposals:
        lines.append(messages.history_row(p))

    await update.message.reply_text("\n".join(lines))


# --- /myproposals ---

async def myproposals_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]
    user = update.effective_user

    proposals = db.get_user_proposals(user.id)
    if not proposals:
        await update.message.reply_text(messages.no_proposals())
        return

    lines = [f"Le tue proposte:\n"]
    for p in proposals:
        lines.append(messages.history_row(p))

    await update.message.reply_text("\n".join(lines))


# --- /status ---

async def status_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Uso: /status <id_proposta>")
        return

    try:
        proposal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID proposta non valido.")
        return

    proposal = db.get_proposal(proposal_id)
    if not proposal:
        await update.message.reply_text(messages.proposal_not_found(proposal_id))
        return

    await update.message.reply_text(messages.proposal_status(proposal))


# --- /balance ---

async def balance_handler(update: Update, context: CallbackContext):
    jetton = context.bot_data.get("jetton")
    if not jetton:
        await update.message.reply_text("Modulo Jetton non configurato.")
        return

    try:
        pal_balance = await jetton.get_pal_balance()
        ton_balance = await jetton.get_ton_balance()
        await update.message.reply_text(messages.treasury_balance(pal_balance, ton_balance))
    except Exception as e:
        logger.error(f"Balance check failed: {e}")
        await update.message.reply_text(f"Errore nel recupero del saldo: {e}")


# --- /matrix ---

async def matrix_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]

    refs = db.get_all_reference_values()
    if not refs:
        await update.message.reply_text("Matrice sociale vuota.")
        return

    lines = [messages.matrix_header()]
    for ref in refs:
        lines.append(messages.matrix_row(ref))

    await update.message.reply_text("\n".join(lines))


# --- /help ---

async def help_handler(update: Update, context: CallbackContext):
    await update.message.reply_text(messages.help_text())


# --- /incentives ---

async def incentives_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]
    incentives = db.get_active_incentives()
    await update.message.reply_text(messages.incentives_list(incentives))


# --- /expire_incentive (admin) ---

async def expire_incentive_handler(update: Update, context: CallbackContext):
    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = update.effective_user

    if not _is_admin(user.id, config):
        await update.message.reply_text(messages.admin_only())
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Uso: /expire_incentive <id>")
        return

    try:
        incentive_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID incentivo non valido.")
        return

    incentive = db.get_incentive(incentive_id)
    if not incentive:
        await update.message.reply_text(messages.incentive_not_found(incentive_id))
        return

    success = db.expire_incentive(incentive_id)
    if success:
        await update.message.reply_text(messages.incentive_expired_msg(incentive_id))
    else:
        await update.message.reply_text(f"Incentivo #{incentive_id} non e' attivo.")
