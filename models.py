from dataclasses import dataclass
from typing import Optional


@dataclass
class Member:
    telegram_user_id: int
    telegram_username: Optional[str]
    ton_address: str
    registered_at: str


@dataclass
class Proposal:
    id: int
    proposer_user_id: int
    event_name: str
    num_participants: int
    pal_per_participant: float
    pal_for_organiser: float
    total_amount: float
    status: str  # awaiting_endorsement / pending / on_hold / approved / rejected / failed
    created_at: str
    endorsed_at: Optional[str] = None
    endorser_user_id: Optional[int] = None
    expires_at: Optional[str] = None
    approved_at: Optional[str] = None
    tx_hash: Optional[str] = None
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    objector_user_id: Optional[int] = None
    objection_reason: Optional[str] = None
    objected_at: Optional[str] = None
    reinstated_at: Optional[str] = None


@dataclass
class LedgerEntry:
    id: int
    proposal_id: int
    amount: float
    tx_hash: Optional[str]
    status: str  # success / failed
    created_at: str


@dataclass
class ReferenceValue:
    id: int
    category: str
    description: str
    pal_per_unit: float
    unit: str
    source: str  # seed / learned
    proposal_id: Optional[int]
    created_at: str
