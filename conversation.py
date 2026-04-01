"""Guided /propose conversation flow using python-telegram-bot ConversationHandler."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters,
)

import messages
from social_matrix import get_references, format_references

logger = logging.getLogger(__name__)

# Conversation states
EVENT_NAME, NUM_PARTICIPANTS, PAL_PER_PARTICIPANT, PAL_FOR_ORGANISER = range(4)


async def propose_start(update: Update, context: CallbackContext) -> int:
    """Entry point: /propose command. Check registration, ask for event name."""
    db = context.bot_data["db"]
    user = update.effective_user
    member = db.get_member(user.id)

    if not member:
        await update.message.reply_text(messages.not_registered())
        return ConversationHandler.END

    # Clear any previous draft
    context.user_data.clear()
    context.user_data["proposer_user_id"] = user.id

    await update.message.reply_text(messages.propose_ask_event())
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
    """Receive organiser PAL, validate total, create proposal and post summary."""
    db = context.bot_data["db"]
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

    # Check max amount
    if total > config["max_proposal_amount"]:
        await update.message.reply_text(
            messages.propose_amount_exceeds_max(config["max_proposal_amount"])
        )
        return PAL_FOR_ORGANISER

    # Post summary first to get message_id
    user = update.effective_user
    proposer_name = f"@{user.username}" if user.username else user.full_name

    # Send a placeholder to get the message_id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Appoggia / Endorse", callback_data="endorse:0")]
    ])
    placeholder = await update.message.reply_text("Creazione proposta...", reply_markup=keyboard)

    # Create proposal in DB
    proposal_id = db.create_proposal(
        proposer_user_id=data["proposer_user_id"],
        event_name=data["event_name"],
        num_participants=num_p,
        pal_per_participant=pal_pp,
        pal_for_organiser=organiser,
        message_id=placeholder.message_id,
        chat_id=update.effective_chat.id,
    )

    # Get the created proposal
    proposal = db.get_proposal(proposal_id)

    # Update the message with actual proposal content
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Appoggia / Endorse", callback_data=f"endorse:{proposal_id}")]
    ])
    await placeholder.edit_text(
        text=messages.propose_summary(proposal, proposer_name),
        reply_markup=keyboard,
    )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancel the conversation."""
    context.user_data.clear()
    await update.message.reply_text("Proposta annullata.")
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
        entry_points=[CommandHandler("propose", propose_start)],
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
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, timeout)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=timeout_seconds,
        per_user=True,
        per_chat=True,
    )
