# PAL Distribution Bot — Rete Palanche di Genova

Telegram bot for distributing PAL social tokens through community consensus. PAL (Palanche) are social tokens produced when group interactions create social value. The bot manages the full lifecycle of token proposals: guided creation, endorsement, no-objection period, and on-chain Jetton transfer on the TON blockchain.

## How It Works

### The PAL Economy

PAL tokens reward social contributions — volunteering, organising events, teaching, community maintenance. The bot anchors valuations through a **social matrix**: a growing reference table seeded with base values (e.g., 1 hour of volunteer work = 1 PAL) that evolves as the community approves proposals.

### Proposal Flow

```
1. Member starts /propose in the group chat
2. Bot guides through: event name → participants → PAL per person → organiser PAL
   (shows social matrix references after event name to help calibrate)
3. Summary posted with "Appoggia / Endorse" button
4. Another member endorses → 24h no-objection countdown starts
5. If no objection after 24h → PAL tokens auto-transferred on-chain
6. If objected (reason mandatory, shown to all) → proposal on hold → admins decide
```

### Consensus Mechanism

- **Endorsement** (anti-spam): A second member must back the proposal before the countdown begins
- **No-objection window** (24h): Any member can object with a mandatory reason. The reason is displayed publicly to the group.
- **On-hold resolution**: Admins can reinstate (fresh 24h countdown) or reject contested proposals

## Commands

| Command | Who | Description |
|---|---|---|
| `/register <TON_address>` | Any member | Link your TON wallet address |
| `/propose` | Registered members | Start a guided proposal (conversational) |
| `/endorse <id>` | Any member | Endorse a proposal awaiting support |
| `/object <id> <reason>` | Any member | Object to a pending proposal (reason required) |
| `/reinstate <id>` | Admin | Reinstate an on-hold proposal (new 24h window) |
| `/reject <id>` | Admin | Reject an on-hold proposal |
| `/history [n]` | Any | Show last n proposals (default 10) |
| `/myproposals` | Any | Show your own proposals |
| `/status <id>` | Any | Show details of a specific proposal |
| `/balance` | Any | Show treasury PAL and TON balances |
| `/matrix` | Any | Show social matrix reference values |
| `/help` | Any | List available commands |

Inline buttons are also available on proposal messages for endorsing and objecting.

## Social Matrix

The social matrix provides reference values to help proposers calibrate their requests. It starts with seed values and grows as proposals are approved.

### Seed Values

| Activity | PAL/unit | Unit |
|---|---|---|
| Lavoro volontario generico | 1.0 | hour |
| Pulizia spazio pubblico | 1.0 | hour |
| Organizzazione laboratorio | 2.0 | event |
| Facilitazione riunione | 1.5 | event |
| Trasporto materiali | 1.0 | hour |
| Preparazione cibo comunitario | 1.0 | hour |
| Insegnamento/tutoring | 1.5 | hour |
| Riparazione/manutenzione | 1.0 | hour |
| Bonus organizzatore evento | 2.0 | event |

Seed values can be customised by editing `seed_values.json` before first run.

### Learning

When a proposal is approved, the bot extracts keywords from the event description and adds the per-participant and organiser values as learned references. Over time, the matrix becomes a community-curated valuation table visible via `/matrix`.

## Design Notes

### Two-Layer Architecture: Governance and Distribution

The bot separates **governance** (who decides) from **distribution** (who receives). The Telegram group is the governance layer — its members propose, endorse, object, and vote. But the PAL network extends well beyond the chat: participants in events, volunteers, and beneficiaries may not be group members at all.

When a proposal is approved, the **full PAL allocation is transferred to the proposer's registered wallet**. The proposer — typically the event organiser — is responsible for redistributing tokens to the actual participants in the wider network. This design is intentional:

- **The network is larger than the chat.** PAL recipients can be anyone with a TON wallet, not just Telegram group members. A cleanup event might involve 20 volunteers, while the governance group has 8 members.
- **The proposer is the trust anchor.** They organised the event, they know the participants, and the group endorsed their proposal. The governance consensus validates the value produced; the proposer handles the last-mile distribution.
- **Simplicity over over-engineering.** Requiring all participants to register with the bot would create friction and exclude people who contribute socially but don't use Telegram.

### What the Bot Tracks vs. What It Doesn't

The bot's ledger records **governance decisions**: which proposals were made, endorsed, objected to, and how many PAL were minted. It does not track downstream redistribution from proposer to participants — that happens wallet-to-wallet on the TON blockchain.

This separation keeps the bot focused and leaves room for complementary tools (block explorer dashboards, network visualisation) to map the full flow of PAL through the community.

### Social Matrix as Collective Memory

The social matrix is not a price list — it's a **collective memory** of how the community has valued different activities over time. Seed values provide initial anchoring (1 hour of volunteer work = 1 PAL), but the real signal comes from approved proposals feeding back into the matrix. Over time, the community implicitly develops shared norms for what different contributions are worth, visible to anyone via `/matrix`.

## Setup

### Prerequisites

- Python 3.10+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A TON wallet with PAL Jetton tokens (the treasury)
- A TonCenter API key (from [toncenter.com](https://toncenter.com))

### Installation

```bash
cd pal-distributor-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Copy and edit the `.env` file with your credentials:

```env
# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...          # From @BotFather
TELEGRAM_GROUP_CHAT_ID=-100123456789           # Your group's chat ID
TELEGRAM_ADMIN_USER_IDS=12345,67890            # Comma-separated admin Telegram user IDs

# TON Network
TON_NETWORK=mainnet                            # or testnet
TON_API_KEY=your_toncenter_api_key
TON_API_URL=https://toncenter.com/api/v2/      # or testnet.toncenter.com for testing

# Treasury Wallet
TREASURY_MNEMONIC=word1 word2 ... word24       # 24-word mnemonic of the treasury wallet
TREASURY_ADDRESS=EQC...                        # Treasury wallet address

# PAL Jetton
JETTON_MASTER_ADDRESS=EQD...                   # PAL Jetton master contract address
PAL_DECIMALS=9                                 # Token decimals (typically 9)

# Proposal Settings
PROPOSAL_EXPIRY_HOURS=24                       # No-objection window duration
ENDORSEMENT_EXPIRY_HOURS=48                    # Time before unendorsed proposals expire
MAX_PROPOSAL_AMOUNT=1000                       # Maximum PAL per proposal
CONVERSATION_TIMEOUT_SECONDS=300               # Timeout for guided /propose flow

# Scheduler
SCHEDULER_INTERVAL_SECONDS=120                 # How often to check for expired proposals

# Database
DB_PATH=data/pal_bot.db                        # SQLite database path
```

**Finding your group chat ID**: Add the bot to your group, send a message, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to see the chat ID (negative number starting with -100).

**Finding Telegram user IDs**: Forward a message from the user to [@userinfobot](https://t.me/userinfobot).

### Running

```bash
source venv/bin/activate
python bot.py
```

The bot will:
1. Initialise the SQLite database (created automatically in `data/`)
2. Load social matrix seed values on first run
3. Start the proposal expiry scheduler
4. Begin polling for Telegram updates

### Running Tests

```bash
source venv/bin/activate
python test_bot.py
```

77 integration tests cover config loading, TON address validation, full proposal lifecycle, social matrix operations, message formatting, and scheduler queries.

## Architecture

```
bot.py               Entry point — wires handlers, scheduler, shared state
config.py            Loads .env into typed config dict
database.py          SQLite schema + CRUD for members, proposals, ledger, social_matrix
models.py            Dataclasses: Proposal, Member, LedgerEntry, ReferenceValue
conversation.py      ConversationHandler for guided /propose flow
handlers.py          Command handlers: /register, /endorse, /object, /reinstate, etc.
social_matrix.py     Keyword extraction, category matching, reference lookup, learning
scheduler.py         Background jobs: auto-approve expired proposals, clean up stale ones
jetton.py            TON Jetton transfer via TonCenter API
messages.py          Italian message templates
utils.py             Address validation, formatting helpers
seed_values.json     Initial social matrix reference values
```

### Database Tables

- **members** — Telegram user ↔ TON wallet mapping
- **proposals** — Full proposal lifecycle with status, endorsement, objection, timestamps
- **ledger** — On-chain transfer log
- **social_matrix** — Reference values (seed + learned from approved proposals)

### Proposal States

```
awaiting_endorsement → pending → approved → (Jetton transfer)
                                    ↓
                         on_hold (objected, reason displayed)
                          ↓              ↓
                     reinstated       rejected
                    (fresh 24h)
```

## Testing on Testnet

For safe testing before mainnet deployment:

1. Set `TON_NETWORK=testnet` and `TON_API_URL=https://testnet.toncenter.com/api/v2/` in `.env`
2. Get testnet TON from [testnet faucet](https://t.me/testgiver_ton_bot)
3. Deploy a test Jetton or use an existing testnet Jetton
4. Set `PROPOSAL_EXPIRY_HOURS=0.05` (3 minutes) for faster testing cycles
5. Create a private Telegram group for testing

## Security Notes

- **Never commit `.env`** — it contains the treasury wallet mnemonic. The `.gitignore` excludes it.
- The treasury wallet holds both PAL tokens and a small TON balance for gas fees. Monitor the TON balance via `/balance` to ensure transfers can proceed.
- Only designated admin user IDs can `/reinstate` or `/reject` proposals.
- The bot validates TON addresses before registration to prevent typos.

## License

This project is developed for Rete Palanche di Genova.
