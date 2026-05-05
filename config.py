import os
from dotenv import load_dotenv


def load_config() -> dict:
    """Load configuration from .env file and return as typed dict."""
    load_dotenv()

    admin_ids_str = os.getenv("TELEGRAM_ADMIN_USER_IDS", "")
    admin_ids = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]

    return {
        # Telegram
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_group_chat_id": int(os.getenv("TELEGRAM_GROUP_CHAT_ID", "0")),
        "telegram_admin_user_ids": admin_ids,
        # TON Network
        "ton_network": os.getenv("TON_NETWORK", "testnet"),
        "ton_api_key": os.getenv("TON_API_KEY", ""),
        "ton_api_url": os.getenv("TON_API_URL", "https://testnet.toncenter.com/api/v2/"),
        # Treasury
        "treasury_mnemonic": os.getenv("TREASURY_MNEMONIC", ""),
        "treasury_address": os.getenv("TREASURY_ADDRESS", ""),
        # PAL Jetton
        "jetton_master_address": os.getenv("JETTON_MASTER_ADDRESS", ""),
        "pal_decimals": int(os.getenv("PAL_DECIMALS", "9")),
        # Proposal settings
        "proposal_expiry_hours": float(os.getenv("PROPOSAL_EXPIRY_HOURS", "24")),
        "endorsement_expiry_hours": float(os.getenv("ENDORSEMENT_EXPIRY_HOURS", "48")),
        "max_proposal_amount": float(os.getenv("MAX_PROPOSAL_AMOUNT", "1000")),
        "propose_cooldown_seconds": int(os.getenv("PROPOSE_COOLDOWN_SECONDS", "3600")),
        "conversation_timeout_seconds": int(os.getenv("CONVERSATION_TIMEOUT_SECONDS", "300")),
        "scheduler_interval_seconds": int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "120")),
        # Database
        "db_path": os.getenv("DB_PATH", "data/pal_bot.db"),
    }
