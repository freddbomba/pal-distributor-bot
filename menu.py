"""Main menu, navigation helpers, and menu callback handlers."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

import messages

logger = logging.getLogger(__name__)


def back_button() -> InlineKeyboardButton:
    return InlineKeyboardButton("🔙 Menu principale", callback_data="menu:main")


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[back_button()]])


def build_main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📋 Proponi distribuzione", callback_data="menu:propose"),
            InlineKeyboardButton("🎁 Proponi incentivo", callback_data="menu:propose_incentive"),
        ],
        [
            InlineKeyboardButton("📜 Cronologia", callback_data="menu:history"),
            InlineKeyboardButton("👤 Mie proposte", callback_data="menu:myproposals"),
        ],
        [
            InlineKeyboardButton("🎯 Incentivi attivi", callback_data="menu:incentives"),
            InlineKeyboardButton("💰 Saldo tesoreria", callback_data="menu:balance"),
        ],
        [
            InlineKeyboardButton("📊 Matrice sociale", callback_data="menu:matrix"),
            InlineKeyboardButton("📝 Registra wallet", callback_data="menu:register"),
        ],
    ]
    if is_admin:
        rows.append([
            InlineKeyboardButton("🔁 Ripristina", callback_data="menu:reinstate"),
            InlineKeyboardButton("❌ Rifiuta", callback_data="menu:reject"),
            InlineKeyboardButton("⏱ Scade incentivo", callback_data="menu:expire_incentive"),
        ])
    return InlineKeyboardMarkup(rows)


async def show_menu(update: Update, context: CallbackContext):
    config = context.bot_data["config"]
    user = update.effective_user
    is_admin = user.id in config["telegram_admin_user_ids"]
    keyboard = build_main_menu(is_admin)
    text = messages.menu_welcome()
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)


async def help_handler(update: Update, context: CallbackContext):
    """Handle /help, /start, /menu — show main menu."""
    await show_menu(update, context)


async def menu_callback_handler(update: Update, context: CallbackContext):
    """Handle all menu: callback buttons (propose/propose_incentive caught by ConversationHandlers)."""
    query = update.callback_query
    await query.answer()

    action = query.data.split(":", 1)[1]
    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = query.from_user

    if action == "main":
        await show_menu(update, context)
        return

    if action == "history":
        proposals = db.get_recent_proposals(10)
        if not proposals:
            await query.edit_message_text(messages.no_proposals(), reply_markup=back_keyboard())
            return
        rows = [[InlineKeyboardButton(
            messages.history_button_label(p), callback_data=f"status:{p.id}"
        )] for p in proposals]
        rows.append([back_button()])
        await query.edit_message_text(
            messages.history_header(len(proposals)),
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if action == "myproposals":
        proposals = db.get_user_proposals(user.id)
        if not proposals:
            await query.edit_message_text(messages.no_proposals(), reply_markup=back_keyboard())
            return
        rows = [[InlineKeyboardButton(
            messages.history_button_label(p), callback_data=f"status:{p.id}"
        )] for p in proposals]
        rows.append([back_button()])
        await query.edit_message_text("Le tue proposte:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "incentives":
        incentives = db.get_active_incentives()
        await query.edit_message_text(
            messages.incentives_list(incentives), reply_markup=back_keyboard()
        )
        return

    if action == "balance":
        jetton = context.bot_data.get("jetton")
        if not jetton:
            await query.edit_message_text(
                "Modulo Jetton non configurato.", reply_markup=back_keyboard()
            )
            return
        try:
            pal_balance = await jetton.get_pal_balance()
            ton_balance = await jetton.get_ton_balance()
            await query.edit_message_text(
                messages.treasury_balance(pal_balance, ton_balance), reply_markup=back_keyboard()
            )
        except Exception as e:
            await query.edit_message_text(
                f"Errore nel recupero del saldo: {e}", reply_markup=back_keyboard()
            )
        return

    if action == "matrix":
        refs = db.get_all_reference_values()
        if not refs:
            await query.edit_message_text("Matrice sociale vuota.", reply_markup=back_keyboard())
            return
        lines = [messages.matrix_header()]
        for ref in refs:
            lines.append(messages.matrix_row(ref))
        await query.edit_message_text("\n".join(lines), reply_markup=back_keyboard())
        return

    if action == "register":
        await query.edit_message_text(
            "Usa /register <indirizzo_TON> per registrare il tuo wallet TON.",
            reply_markup=back_keyboard(),
        )
        return

    if action in ("reinstate", "reject"):
        if user.id not in config["telegram_admin_user_ids"]:
            await query.edit_message_text(messages.admin_only(), reply_markup=back_keyboard())
            return
        proposals = db.get_proposals_by_status("on_hold")
        if not proposals:
            await query.edit_message_text(
                "Nessuna proposta in sospeso.", reply_markup=back_keyboard()
            )
            return
        rows = [[InlineKeyboardButton(
            messages.history_button_label(p), callback_data=f"status:{p.id}"
        )] for p in proposals]
        rows.append([back_button()])
        label = (
            "Seleziona la proposta da ripristinare:"
            if action == "reinstate"
            else "Seleziona la proposta da rifiutare:"
        )
        await query.edit_message_text(label, reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "expire_incentive":
        if user.id not in config["telegram_admin_user_ids"]:
            await query.edit_message_text(messages.admin_only(), reply_markup=back_keyboard())
            return
        incentives = db.get_active_incentives()
        if not incentives:
            await query.edit_message_text("Nessun incentivo attivo.", reply_markup=back_keyboard())
            return
        rows = [[InlineKeyboardButton(
            f"#{inc.id} — {inc.offered_by}: {inc.description[:30]}",
            callback_data=f"expire_incentive:{inc.id}",
        )] for inc in incentives]
        rows.append([back_button()])
        await query.edit_message_text(
            "Seleziona l'incentivo da scadere:", reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # Fallback for propose/propose_incentive if not caught by ConversationHandler
    await show_menu(update, context)


async def status_callback_handler(update: Update, context: CallbackContext):
    """Handle status:<id> button — proposal details with contextual action buttons."""
    query = update.callback_query
    await query.answer()

    db = context.bot_data["db"]
    config = context.bot_data["config"]
    user = query.from_user
    is_admin = user.id in config["telegram_admin_user_ids"]

    proposal_id = int(query.data.split(":")[1])
    proposal = db.get_proposal(proposal_id)

    if not proposal:
        await query.edit_message_text(
            messages.proposal_not_found(proposal_id), reply_markup=back_keyboard()
        )
        return

    action_buttons = []
    if proposal.status == "awaiting_endorsement" and user.id != proposal.proposer_user_id:
        action_buttons.append(
            InlineKeyboardButton("Appoggia", callback_data=f"endorse:{proposal_id}")
        )
    if proposal.status == "pending" and user.id != proposal.proposer_user_id:
        action_buttons.append(
            InlineKeyboardButton("Obietta", callback_data=f"object:{proposal_id}")
        )
    if proposal.status == "on_hold" and is_admin:
        action_buttons.append(
            InlineKeyboardButton("🔁 Ripristina", callback_data=f"reinstate:{proposal_id}")
        )
        action_buttons.append(
            InlineKeyboardButton("❌ Rifiuta", callback_data=f"reject:{proposal_id}")
        )

    rows = []
    if action_buttons:
        rows.append(action_buttons)
    rows.append([back_button()])

    await query.edit_message_text(
        messages.proposal_status(proposal),
        reply_markup=InlineKeyboardMarkup(rows),
    )
