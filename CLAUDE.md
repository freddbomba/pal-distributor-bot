# pal-distributor-bot

## What This Is
Telegram bot implementing request/approve workflow for PAL token distribution.
Incentives CRUD, full Italian localization.

## Quick Commands
- Run tests: `pytest` (48-test suite)
- Deploy: copy to lanterna-bot:/opt/telegram-bot/pal-distributor-bot/

## Architecture
- Single Python bot, python-telegram-bot library
- .env config: Telegram token, group chat ID, admin IDs, TON API key, treasury mnemonic/address

## Current State
- Merged master → main on GitHub (freddbomba/pal-distributor-bot)
- Deployed in lanterna-bot container
- Working: request flow, approval flow, incentives CRUD

## Active TODOs
- [list the specific things you're working on next]

## Rules
- Never commit .env or mnemonic values
- Test before deploying

