"""Guided /propose conversation flow using python-telegram-bot ConversationHandler."""

import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    CallbackContext,
    filters,
)

import messages
from menu import back_keyboard
from social_matrix import get_references, format_references

logger = logging.getLogger(__name__)

# Conversation states
EVENT_NAME, NUM_PARTICIPANTS, PAL_PER_PARTICIPANT, PAL_FOR_ORGANISER, CONFIRM = range(5)


async def propose_start(update: Update, context: CallbackContext) -> int:
    """Entry point: /propose command or menu:propose button."""
    db = context.bot_data["db"]
    user = update.effective_user
    chat = update.effective_chat
    member = db.get_member(user.id)

    is_callback = update.callback_query is not None
    if is_callback:
        await update.callback_query.answer()

    async def reply(text):
        if is_callback:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)

    if not member:
        await reply(messages.not_registered())
        return ConversationHandler.END

    config = context.bot_data['config']
    cooldown = config['propose_cooldown_seconds']
    rate_limits = context.bot_data.setdefault('rate_limits', {})
    last_time = rate_limits.get(user.id, 0)
    elapsed = time.time() - last_time
    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        await reply(messages.propose_cooldown(remaining))
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["proposer_user_id"] = user.id

    if chat.type in ("group", "supergroup"):
        await reply(messages.propose_redirecting_to_dm())
        try:
            await context.bot.send_message(chat_id=user.id, text=messages.propose_ask_event())
        except Exception:
            await context.bot.send_message(
                chat_id=chat.id,
                text=messages.propose_dm_failed(context.bot.username),
            )
            return ConversationHandler.END
    else:
        await reply(messages.propose_ask_event())

    return EVENT_NAME


async def receive_event_name(update: Update, context: CallbackContext) -> int:
    """Receive event name, show social matrix references, ask for participant count."""
    db = context.bot_data["db"]
    event_name = update.message.text.strip()

    if not event_name:
        await update.message.reply_text(messages.propose_ask_event())
        return EVENT_NAME

    context.user_data["event_name"] = event_name

    # Show social matrix references
    ref_values, past_proposals = get_references(db, event_name)
    refs_text = format_references(ref_values, past_proposals)

    if refs_text:
        await update.message.reply_text(refs_text)

    await update.message.reply_text(messages.propose_ask_participants())
    return NUM_PARTICIPANTS


async def receive_num_participants(update: Update, context: CallbackContext) -> int:
    """Receive number of participants, ask for PAL per participant."""
    try:
        num = int(update.message.text.strip())
        if num <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await update.message.reply_text(messages.propose_invalid_number())
        return NUM_PARTICIPANTS

    context.user_data["num_participants"] = num
    await update.message.reply_text(messages.propose_ask_pal_per_participant())
    return PAL_PER_PARTICIPANT


async def receive_pal_per_participant(update: Update, context: CallbackContext) -> int:
    """Receive PAL per participant, ask for organiser PAL."""
    try:
        amount = float(update.message.text.strip())
        if amount < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await update.message.reply_text(messages.propose_invalid_number())
        return PAL_PER_PARTICIPANT

    context.user_data["pal_per_participant"] = amount
    await update.message.reply_text(messages.propose_ask_pal_organiser())
    return PAL_FOR_ORGANISER


async def receive_pal_organiser(update: Update, context: CallbackContext) -> int:
    """Receive organiser PAL, validate total, show confirmation recap."""
    config = context.bot_data["config"]

    try:
        organiser = float(update.message.text.strip())
        if organiser < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await update.message.reply_text(messages.propose_invalid_number())
        return PAL_FOR_ORGANISER

    data = context.user_data
    num_p = data["num_participants"]
    pal_pp = data["pal_per_participant"]
    total = (num_p * pal_pp) + organiser

    if total > config["max_proposal_amount"]:
        await update.message.reply_text(
            messages.propose_amount_exceeds_max(config["max_proposal_amount"])
        )
        return PAL_FOR_ORGANISER

    context.user_data["pal_for_organiser"] = organiser
    context.user_data["total"] = total

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Conferma", callback_data="propose_confirm"),
        InlineKeyboardButton("❌ Annulla", callback_data="propose_abort"),
    ]])
    await update.message.reply_text(
        messages.propose_confirm_summary(data["event_name"], num_p, pal_pp, organiser, total),
        reply_markup=keyboard,
    )
    return CONFIRM


async def confirm_proposal(update: Update, context: CallbackContext) -> int:
    """User confirmed — post proposal to group, confirm in DM."""
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = query.from_user
    data = context.user_data
    group_chat_id = config["telegram_group_chat_id"]

    proposer_name = f"@{user.username}" if user.username else user.full_name

    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Appoggia", callback_data="endorse:0")]
        ])
        placeholder = await context.bot.send_message(
            chat_id=group_chat_id,
            text="Creazione proposta...",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error("Failed to post proposal to group %s: %s", group_chat_id, e)
        await query.edit_message_text(
            f"Errore: non riesco a pubblicare nel gruppo. "
            f"Verifica che il bot sia membro del gruppo e abbia i permessi per inviare messaggi."
        )
        context.user_data.clear()
        return ConversationHandler.END

    rate_limits = context.bot_data.setdefault('rate_limits', {})
    rate_limits[user.id] = time.time()

    proposal_id = db.create_proposal(
        proposer_user_id=data["proposer_user_id"],
        event_name=data["event_name"],
        num_participants=data["num_participants"],
        pal_per_participant=data["pal_per_participant"],
        pal_for_organiser=data["pal_for_organiser"],
        message_id=placeholder.message_id,
        chat_id=group_chat_id,
    )

    proposal = db.get_proposal(proposal_id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Appoggia", callback_data=f"endorse:{proposal_id}")]
    ])
    await placeholder.edit_text(
        text=messages.propose_summary(proposal, proposer_name),
        reply_markup=keyboard,
    )

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(messages.propose_sent_to_group(), reply_markup=back_keyboard())
    context.user_data.clear()
    return ConversationHandler.END


async def abort_proposal(update: Update, context: CallbackContext) -> int:
    """User aborted — discard draft, no rate limit tick."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(messages.propose_cancelled())
    return ConversationHandler.END


async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancel the conversation via /cancel command."""
    context.user_data.clear()
    await update.message.reply_text(messages.propose_cancelled())
    return ConversationHandler.END


async def timeout(update: Update, context: CallbackContext) -> int:
    """Handle conversation timeout."""
    context.user_data.clear()
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.propose_timeout(),
        )
    return ConversationHandler.END


def build_conversation_handler(timeout_seconds: int) -> ConversationHandler:
    """Build and return the ConversationHandler for /propose."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("propose", propose_start),
            CallbackQueryHandler(propose_start, pattern=r"^menu:propose$"),
        ],
        states={
            EVENT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_event_name)
            ],
            NUM_PARTICIPANTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_num_participants)
            ],
            PAL_PER_PARTICIPANT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_pal_per_participant)
            ],
            PAL_FOR_ORGANISER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_pal_organiser)
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_proposal, pattern=r"^propose_confirm$"),
                CallbackQueryHandler(abort_proposal, pattern=r"^propose_abort$"),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, timeout)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=timeout_seconds,
        per_user=True,
        per_chat=False,
        per_message=False,
    )
