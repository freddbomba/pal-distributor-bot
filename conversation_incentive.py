"""Guided /propose_incentive conversation flow."""

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

logger = logging.getLogger(__name__)

OFFERED_BY, INCENTIVE_DESC, CONDITIONS, CONFIRM = range(4)


async def propose_incentive_start(update: Update, context: CallbackContext) -> int:
    """Entry point: /propose_incentive or menu:propose_incentive button."""
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
            await context.bot.send_message(
                chat_id=user.id,
                text=messages.propose_incentive_ask_offered_by(),
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat.id,
                text=messages.propose_dm_failed(context.bot.username),
            )
            return ConversationHandler.END
    else:
        await reply(messages.propose_incentive_ask_offered_by())

    return OFFERED_BY


async def receive_offered_by(update: Update, context: CallbackContext) -> int:
    offered_by = update.message.text.strip()
    if not offered_by:
        await update.message.reply_text(messages.propose_incentive_ask_offered_by())
        return OFFERED_BY

    context.user_data["incentive_offered_by"] = offered_by
    await update.message.reply_text(messages.propose_incentive_ask_description())
    return INCENTIVE_DESC


async def receive_incentive_desc(update: Update, context: CallbackContext) -> int:
    description = update.message.text.strip()
    if not description:
        await update.message.reply_text(messages.propose_incentive_ask_description())
        return INCENTIVE_DESC

    context.user_data["incentive_description"] = description
    await update.message.reply_text(messages.propose_incentive_ask_conditions())
    return CONDITIONS


async def receive_conditions(update: Update, context: CallbackContext) -> int:
    """Receive conditions, show confirmation recap."""
    conditions = update.message.text.strip()

    if not conditions:
        await update.message.reply_text(messages.propose_incentive_ask_conditions())
        return CONDITIONS

    context.user_data["incentive_conditions"] = conditions
    data = context.user_data

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Conferma", callback_data="incentive_confirm"),
        InlineKeyboardButton("❌ Annulla", callback_data="incentive_abort"),
    ]])
    await update.message.reply_text(
        messages.incentive_confirm_summary(
            data["incentive_offered_by"],
            data["incentive_description"],
            data["incentive_conditions"],
        ),
        reply_markup=keyboard,
    )
    return CONFIRM


async def confirm_incentive_proposal(update: Update, context: CallbackContext) -> int:
    """User confirmed — post incentive proposal to group, confirm in DM."""
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = query.from_user
    data = context.user_data
    group_chat_id = config["telegram_group_chat_id"]

    rate_limits = context.bot_data.setdefault('rate_limits', {})
    rate_limits[user.id] = time.time()

    proposer_name = f"@{user.username}" if user.username else user.full_name

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Appoggia", callback_data="endorse:0")]
    ])
    placeholder = await context.bot.send_message(
        chat_id=group_chat_id,
        text="Creazione proposta incentivo...",
        reply_markup=keyboard,
    )

    event_name = f"[Incentivo] {data['incentive_description'][:60]}"
    proposal_id = db.create_proposal(
        proposer_user_id=data["proposer_user_id"],
        event_name=event_name,
        num_participants=0,
        pal_per_participant=0.0,
        pal_for_organiser=0.0,
        message_id=placeholder.message_id,
        chat_id=group_chat_id,
        proposal_type="incentive",
        incentive_offered_by=data["incentive_offered_by"],
        incentive_description=data["incentive_description"],
        incentive_conditions=data["incentive_conditions"],
    )

    proposal = db.get_proposal(proposal_id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Appoggia", callback_data=f"endorse:{proposal_id}")]
    ])
    await placeholder.edit_text(
        text=messages.propose_incentive_summary(proposal, proposer_name),
        reply_markup=keyboard,
    )

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(messages.propose_sent_to_group(), reply_markup=back_keyboard())
    context.user_data.clear()
    return ConversationHandler.END


async def abort_incentive_proposal(update: Update, context: CallbackContext) -> int:
    """User aborted — discard draft, no rate limit tick."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(messages.propose_cancelled())
    return ConversationHandler.END


async def cancel_incentive(update: Update, context: CallbackContext) -> int:
    context.user_data.clear()
    await update.message.reply_text(messages.propose_cancelled())
    return ConversationHandler.END


async def timeout_incentive(update: Update, context: CallbackContext) -> int:
    context.user_data.clear()
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.propose_timeout(),
        )
    return ConversationHandler.END


def build_incentive_conversation_handler(timeout_seconds: int) -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("propose_incentive", propose_incentive_start),
            CallbackQueryHandler(propose_incentive_start, pattern=r"^menu:propose_incentive$"),
        ],
        states={
            OFFERED_BY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_offered_by)
            ],
            INCENTIVE_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_incentive_desc)
            ],
            CONDITIONS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_conditions)
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_incentive_proposal, pattern=r"^incentive_confirm$"),
                CallbackQueryHandler(abort_incentive_proposal, pattern=r"^incentive_abort$"),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, timeout_incentive)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_incentive)],
        conversation_timeout=timeout_seconds,
        per_user=True,
        per_chat=False,
        per_message=False,
    )
