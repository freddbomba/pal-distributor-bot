import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from models import Member, Proposal, LedgerEntry, ReferenceValue, Incentive


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def initialize(self):
        """Create all tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS members (
                telegram_user_id   INTEGER PRIMARY KEY,
                telegram_username  TEXT,
                ton_address        TEXT NOT NULL,
                registered_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS proposals (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                proposer_user_id   INTEGER NOT NULL REFERENCES members(telegram_user_id),
                event_name         TEXT NOT NULL,
                num_participants   INTEGER NOT NULL,
                pal_per_participant REAL NOT NULL,
                pal_for_organiser  REAL NOT NULL,
                total_amount       REAL NOT NULL,
                status             TEXT NOT NULL DEFAULT 'awaiting_endorsement',
                created_at         TEXT NOT NULL DEFAULT (datetime('now')),
                endorsed_at        TEXT,
                endorser_user_id   INTEGER,
                expires_at         TEXT,
                approved_at        TEXT,
                tx_hash            TEXT,
                message_id         INTEGER,
                chat_id            INTEGER,
                objector_user_id   INTEGER,
                objection_reason   TEXT,
                objected_at        TEXT,
                reinstated_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS ledger (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id        INTEGER NOT NULL REFERENCES proposals(id),
                amount             REAL NOT NULL,
                tx_hash            TEXT,
                status             TEXT NOT NULL,
                created_at         TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS social_matrix (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                category           TEXT NOT NULL,
                description        TEXT NOT NULL,
                pal_per_unit       REAL NOT NULL,
                unit               TEXT NOT NULL,
                source             TEXT NOT NULL DEFAULT 'seed',
                proposal_id        INTEGER REFERENCES proposals(id),
                created_at         TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS incentives (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                offered_by  TEXT NOT NULL,
                conditions  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'active',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                proposal_id INTEGER REFERENCES proposals(id)
            );
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Add columns introduced after the initial schema without breaking existing data."""
        migrations = [
            "ALTER TABLE proposals ADD COLUMN proposal_type TEXT NOT NULL DEFAULT 'pal_distribution'",
            "ALTER TABLE proposals ADD COLUMN incentive_offered_by TEXT",
            "ALTER TABLE proposals ADD COLUMN incentive_description TEXT",
            "ALTER TABLE proposals ADD COLUMN incentive_conditions TEXT",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
            except Exception:
                pass  # column already exists
        self.conn.commit()

    def load_seed_values(self, seed_file: str):
        """Load seed values into social_matrix if no seed entries exist yet."""
        count = self.conn.execute(
            "SELECT COUNT(*) FROM social_matrix WHERE source = 'seed'"
        ).fetchone()[0]
        if count > 0:
            return

        with open(seed_file, "r", encoding="utf-8") as f:
            seeds = json.load(f)

        for entry in seeds:
            self.conn.execute(
                "INSERT INTO social_matrix (category, description, pal_per_unit, unit, source) "
                "VALUES (?, ?, ?, ?, 'seed')",
                (entry["category"], entry["description"], entry["pal_per_unit"], entry["unit"]),
            )
        self.conn.commit()

    # --- Members ---

    def upsert_member(self, user_id: int, username: Optional[str], ton_address: str):
        self.conn.execute(
            "INSERT INTO members (telegram_user_id, telegram_username, ton_address) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(telegram_user_id) DO UPDATE SET "
            "telegram_username = excluded.telegram_username, ton_address = excluded.ton_address",
            (user_id, username, ton_address),
        )
        self.conn.commit()

    def get_member(self, user_id: int) -> Optional[Member]:
        row = self.conn.execute(
            "SELECT * FROM members WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return None
        return Member(**dict(row))

    # --- Proposals ---

    def create_proposal(
        self,
        proposer_user_id: int,
        event_name: str,
        num_participants: int,
        pal_per_participant: float,
        pal_for_organiser: float,
        message_id: int,
        chat_id: int,
        proposal_type: str = 'pal_distribution',
        incentive_offered_by: Optional[str] = None,
        incentive_description: Optional[str] = None,
        incentive_conditions: Optional[str] = None,
    ) -> int:
        total = (num_participants * pal_per_participant) + pal_for_organiser
        cursor = self.conn.execute(
            "INSERT INTO proposals "
            "(proposer_user_id, event_name, num_participants, pal_per_participant, "
            "pal_for_organiser, total_amount, message_id, chat_id, proposal_type, "
            "incentive_offered_by, incentive_description, incentive_conditions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (proposer_user_id, event_name, num_participants, pal_per_participant,
             pal_for_organiser, total, message_id, chat_id, proposal_type,
             incentive_offered_by, incentive_description, incentive_conditions),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_proposal(self, proposal_id: int) -> Optional[Proposal]:
        row = self.conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if not row:
            return None
        return Proposal(**dict(row))

    def endorse_proposal(self, proposal_id: int, endorser_user_id: int, expiry_hours: float):
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=expiry_hours)
        affected = self.conn.execute(
            "UPDATE proposals SET status = 'pending', endorsed_at = ?, "
            "endorser_user_id = ?, expires_at = ? "
            "WHERE id = ? AND status = 'awaiting_endorsement'",
            (now.isoformat(), endorser_user_id, expires_at.isoformat(), proposal_id),
        ).rowcount
        self.conn.commit()
        return affected > 0

    def object_proposal(self, proposal_id: int, objector_user_id: int, reason: str):
        now = datetime.utcnow()
        affected = self.conn.execute(
            "UPDATE proposals SET status = 'on_hold', objector_user_id = ?, "
            "objection_reason = ?, objected_at = ?, expires_at = NULL "
            "WHERE id = ? AND status = 'pending'",
            (objector_user_id, reason, now.isoformat(), proposal_id),
        ).rowcount
        self.conn.commit()
        return affected > 0

    def reinstate_proposal(self, proposal_id: int, expiry_hours: float):
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=expiry_hours)
        affected = self.conn.execute(
            "UPDATE proposals SET status = 'pending', reinstated_at = ?, "
            "expires_at = ?, objector_user_id = NULL, objection_reason = NULL, objected_at = NULL "
            "WHERE id = ? AND status = 'on_hold'",
            (now.isoformat(), expires_at.isoformat(), proposal_id),
        ).rowcount
        self.conn.commit()
        return affected > 0

    def reject_proposal(self, proposal_id: int):
        affected = self.conn.execute(
            "UPDATE proposals SET status = 'rejected' WHERE id = ? AND status = 'on_hold'",
            (proposal_id,),
        ).rowcount
        self.conn.commit()
        return affected > 0

    def approve_proposal(self, proposal_id: int, tx_hash: Optional[str] = None):
        """Mark proposal as approved after successful Jetton transfer."""
        now = datetime.utcnow()
        affected = self.conn.execute(
            "UPDATE proposals SET status = 'approved', approved_at = ?, tx_hash = ? "
            "WHERE id = ? AND status = 'pending'",
            (now.isoformat(), tx_hash, proposal_id),
        ).rowcount
        self.conn.commit()
        return affected > 0

    def fail_proposal(self, proposal_id: int):
        self.conn.execute(
            "UPDATE proposals SET status = 'failed' WHERE id = ?",
            (proposal_id,),
        )
        self.conn.commit()

    def get_expired_pending_proposals(self) -> list[Proposal]:
        now = datetime.utcnow().isoformat()
        rows = self.conn.execute(
            "SELECT * FROM proposals WHERE status = 'pending' AND expires_at <= ?",
            (now,),
        ).fetchall()
        return [Proposal(**dict(r)) for r in rows]

    def get_stale_awaiting_proposals(self, expiry_hours: float) -> list[Proposal]:
        cutoff = (datetime.utcnow() - timedelta(hours=expiry_hours)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM proposals WHERE status = 'awaiting_endorsement' AND created_at <= ?",
            (cutoff,),
        ).fetchall()
        return [Proposal(**dict(r)) for r in rows]

    def expire_proposal(self, proposal_id: int):
        self.conn.execute(
            "UPDATE proposals SET status = 'rejected' "
            "WHERE id = ? AND status = 'awaiting_endorsement'",
            (proposal_id,),
        )
        self.conn.commit()

    def get_recent_proposals(self, limit: int = 10) -> list[Proposal]:
        rows = self.conn.execute(
            "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Proposal(**dict(r)) for r in rows]

    def get_user_proposals(self, user_id: int) -> list[Proposal]:
        rows = self.conn.execute(
            "SELECT * FROM proposals WHERE proposer_user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [Proposal(**dict(r)) for r in rows]

    def get_proposals_by_status(self, status: str) -> list[Proposal]:
        rows = self.conn.execute(
            "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
        return [Proposal(**dict(r)) for r in rows]

    def update_proposal_message(self, proposal_id: int, message_id: int):
        self.conn.execute(
            "UPDATE proposals SET message_id = ? WHERE id = ?",
            (message_id, proposal_id),
        )
        self.conn.commit()

    # --- Ledger ---

    def insert_ledger_entry(self, proposal_id: int, amount: float, tx_hash: str, status: str):
        self.conn.execute(
            "INSERT INTO ledger (proposal_id, amount, tx_hash, status) VALUES (?, ?, ?, ?)",
            (proposal_id, amount, tx_hash, status),
        )
        self.conn.commit()

    # --- Social Matrix ---

    def get_all_reference_values(self) -> list[ReferenceValue]:
        rows = self.conn.execute(
            "SELECT * FROM social_matrix ORDER BY source, category"
        ).fetchall()
        return [ReferenceValue(**dict(r)) for r in rows]

    def search_reference_values(self, keywords: list[str]) -> list[ReferenceValue]:
        """Search social_matrix for entries matching any of the given keywords."""
        if not keywords:
            return []
        conditions = " OR ".join(["category LIKE ? OR description LIKE ?"] * len(keywords))
        params = []
        for kw in keywords:
            pattern = f"%{kw}%"
            params.extend([pattern, pattern])
        rows = self.conn.execute(
            f"SELECT * FROM social_matrix WHERE {conditions} ORDER BY source, pal_per_unit DESC",
            params,
        ).fetchall()
        return [ReferenceValue(**dict(r)) for r in rows]

    def search_approved_proposals(self, keywords: list[str], limit: int = 5) -> list[Proposal]:
        """Search approved proposals with event names matching keywords."""
        if not keywords:
            return []
        conditions = " OR ".join(["event_name LIKE ?"] * len(keywords))
        params = [f"%{kw}%" for kw in keywords]
        rows = self.conn.execute(
            f"SELECT * FROM proposals WHERE status = 'approved' AND ({conditions}) "
            f"ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [Proposal(**dict(r)) for r in rows]

    def add_learned_value(
        self, category: str, description: str, pal_per_unit: float, unit: str, proposal_id: int
    ):
        self.conn.execute(
            "INSERT INTO social_matrix (category, description, pal_per_unit, unit, source, proposal_id) "
            "VALUES (?, ?, ?, ?, 'learned', ?)",
            (category, description, pal_per_unit, unit, proposal_id),
        )
        self.conn.commit()

    # --- Incentives ---

    def create_incentive(
        self, description: str, offered_by: str, conditions: str, proposal_id: int
    ) -> int:
        cursor = self.conn.execute(
            "INSERT INTO incentives (description, offered_by, conditions, proposal_id) "
            "VALUES (?, ?, ?, ?)",
            (description, offered_by, conditions, proposal_id),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_active_incentives(self) -> list[Incentive]:
        rows = self.conn.execute(
            "SELECT * FROM incentives WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall()
        return [Incentive(**dict(r)) for r in rows]

    def get_incentive(self, incentive_id: int) -> Optional[Incentive]:
        row = self.conn.execute(
            "SELECT * FROM incentives WHERE id = ?", (incentive_id,)
        ).fetchone()
        if not row:
            return None
        return Incentive(**dict(row))

    def expire_incentive(self, incentive_id: int) -> bool:
        affected = self.conn.execute(
            "UPDATE incentives SET status = 'expired' WHERE id = ? AND status = 'active'",
            (incentive_id,),
        ).rowcount
        self.conn.commit()
        return affected > 0
