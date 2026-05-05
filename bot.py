"""Entry point for the PAL distribution Telegram bot."""

import logging
import os

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)

from config import load_config
from database import Database
from jetton import JettonTransfer
from conversation import build_conversation_handler
from conversation_incentive import build_incentive_conversation_handler
from handlers import (
    register_handler,
    endorse_command_handler,
    endorse_callback_handler,
    object_command_handler,
    object_callback_handler,
    reinstate_handler,
    reject_handler,
    history_handler,
    myproposals_handler,
    balance_handler,
    status_handler,
    matrix_handler,
    help_handler,
    incentives_handler,
    expire_incentive_handler,
)
from scheduler import check_expired_proposals

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    config = load_config()

    if not config["telegram_bot_token"]:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        return

    # Initialize database
    db = Database(config["db_path"])
    db.initialize()

    # Load seed values for social matrix
    seed_file = os.path.join(os.path.dirname(__file__), "seed_values.json")
    if os.path.exists(seed_file):
        db.load_seed_values(seed_file)
        logger.info("Social matrix seed values loaded")

    # Initialize Jetton client (may fail if not configured yet)
    jetton = None
    if config["treasury_mnemonic"] and config["jetton_master_address"]:
        try:
            jetton = JettonTransfer(config)
            logger.info("Jetton transfer module initialized")
        except Exception as e:
            logger.warning(f"Jetton module not available: {e}")
    else:
        logger.warning("Treasury mnemonic or Jetton address not configured — transfers disabled")

    # Build Telegram application
    app = ApplicationBuilder().token(config["telegram_bot_token"]).build()

    # Store shared resources
    app.bot_data["db"] = db
    app.bot_data["jetton"] = jetton
    app.bot_data["config"] = config

    # Register conversation handlers (must be added before generic command handlers)
    conv_handler = build_conversation_handler(config["conversation_timeout_seconds"])
    app.add_handler(conv_handler)

    incentive_conv_handler = build_incentive_conversation_handler(config["conversation_timeout_seconds"])
    app.add_handler(incentive_conv_handler)

    # Register command handlers
    app.add_handler(CommandHandler("register", register_handler))
    app.add_handler(CommandHandler("endorse", endorse_command_handler))
    app.add_handler(CommandHandler("object", object_command_handler))
    app.add_handler(CommandHandler("reinstate", reinstate_handler))
    app.add_handler(CommandHandler("reject", reject_handler))
    app.add_handler(CommandHandler("history", history_handler))
    app.add_handler(CommandHandler("myproposals", myproposals_handler))
    app.add_handler(CommandHandler("balance", balance_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("matrix", matrix_handler))
    app.add_handler(CommandHandler("incentives", incentives_handler))
    app.add_handler(CommandHandler("expire_incentive", expire_incentive_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("start", help_handler))

    # Register inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(endorse_callback_handler, pattern=r"^endorse:\d+$"))
    app.add_handler(CallbackQueryHandler(object_callback_handler, pattern=r"^object:\d+$"))

    # Start scheduler for auto-approval
    app.job_queue.run_repeating(
        callback=check_expired_proposals,
        interval=config["scheduler_interval_seconds"],
        first=10,
    )
    logger.info(
        f"Scheduler started: checking every {config['scheduler_interval_seconds']}s"
    )

    # Start polling
    logger.info("PAL Distribution Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
