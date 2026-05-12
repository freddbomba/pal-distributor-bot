"""TON Jetton transfer logic for PAL token distribution."""

import logging
import struct
from typing import Optional

import aiohttp
from tonsdk.contract.wallet import Wallets, WalletVersionEnum
from tonsdk.boc import Cell, begin_cell
from tonsdk.utils import to_nano, bytes_to_b64str, Address

logger = logging.getLogger(__name__)

# Jetton transfer opcode
JETTON_TRANSFER_OP = 0x0F8A7EA5


class JettonTransfer:
    def __init__(self, config: dict):
        self.jetton_master_address = config["jetton_master_address"]
        self.treasury_mnemonic = config["treasury_mnemonic"].split()
        self.treasury_address = config["treasury_address"]
        self.ton_api_url = config["ton_api_url"].rstrip("/")
        self.ton_api_key = config["ton_api_key"]
        self.pal_decimals = config["pal_decimals"]

        self._wallet = None  # initialized lazily in _get_wallet()

    def _get_wallet(self):
        if self._wallet is None:
            _mnemonics, _pub_k, _priv_k, self._wallet = Wallets.from_mnemonics(
                self.treasury_mnemonic, WalletVersionEnum.v4r2, 0
            )
        return self._wallet

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.ton_api_key:
            headers["X-API-Key"] = self.ton_api_key
        return headers

    async def _api_get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{self.ton_api_url}/{endpoint}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(), params=params) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    raise RuntimeError(f"TonCenter API error: {data}")
                return data["result"]

    async def _api_post(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.ton_api_url}/{endpoint}"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    raise RuntimeError(f"TonCenter API error: {data}")
                return data["result"]

    async def get_jetton_wallet_address(self, owner_address: str) -> str:
        """Get the Jetton wallet address for a given owner by calling get_wallet_address on the Jetton master."""
        result = await self._api_post("runGetMethod", {
            "address": self.jetton_master_address,
            "method": "get_wallet_address",
            "stack": [
                ["tvm.Slice", self._address_to_slice_b64(owner_address)]
            ],
        })
        # Result stack contains the Jetton wallet address as a cell/slice
        stack = result.get("stack", [])
        if stack and len(stack) > 0:
            # Parse address from the returned cell
            addr_cell_b64 = stack[0][1].get("bytes", "") if isinstance(stack[0][1], dict) else stack[0][1]
            return self._parse_address_from_cell(addr_cell_b64)
        raise RuntimeError("Could not determine Jetton wallet address")

    def _address_to_slice_b64(self, address: str) -> str:
        """Convert a TON address to a base64-encoded cell for API calls."""
        addr = Address(address)
        cell = begin_cell().store_address(addr).end_cell()
        return bytes_to_b64str(cell.to_boc())

    def _parse_address_from_cell(self, cell_b64: str) -> str:
        """Parse a TON address from a base64-encoded cell returned by API."""
        import base64
        boc_bytes = base64.b64decode(cell_b64)
        cell = Cell.one_from_boc(boc_bytes)
        # Read address from cell slice
        cs = cell.begin_parse()
        addr = cs.read_msg_addr()
        return addr.to_string(True, True, True)  # user-friendly, bounceable

    def _build_jetton_transfer_body(
        self,
        to_address: str,
        amount_raw: int,
        response_address: str,
        query_id: int = 0,
        forward_ton_amount: int = 1,  # minimal forward for notification
    ) -> Cell:
        """Build the internal message body for a Jetton transfer."""
        dest_addr = Address(to_address)
        resp_addr = Address(response_address)

        body = (
            begin_cell()
            .store_uint(JETTON_TRANSFER_OP, 32)  # op
            .store_uint(query_id, 64)             # query_id
            .store_coins(amount_raw)              # amount of Jettons
            .store_address(dest_addr)             # destination
            .store_address(resp_addr)             # response_destination
            .store_bit(0)                         # custom_payload (null)
            .store_coins(forward_ton_amount)      # forward_ton_amount
            .store_bit(0)                         # forward_payload (null)
            .end_cell()
        )
        return body

    async def get_seqno(self) -> int:
        """Get current sequence number for the treasury wallet."""
        result = await self._api_post("runGetMethod", {
            "address": self.treasury_address,
            "method": "seqno",
            "stack": [],
        })
        stack = result.get("stack", [])
        if stack:
            return int(stack[0][1], 16) if isinstance(stack[0][1], str) else int(stack[0][1])
        return 0

    async def send_pal_tokens(self, to_address: str, amount: float) -> str:
        """Execute a PAL Jetton transfer from treasury to recipient.

        Args:
            to_address: Recipient's TON wallet address
            amount: Amount of PAL tokens to send

        Returns:
            A message hash string on success

        Raises:
            RuntimeError on failure
        """
        # Convert amount to raw (smallest unit)
        amount_raw = int(amount * (10 ** self.pal_decimals))

        # Get treasury's Jetton wallet address
        jetton_wallet_addr = await self.get_jetton_wallet_address(self.treasury_address)
        logger.info(f"Treasury Jetton wallet: {jetton_wallet_addr}")

        # Build Jetton transfer body
        body = self._build_jetton_transfer_body(
            to_address=to_address,
            amount_raw=amount_raw,
            response_address=self.treasury_address,
        )

        # Get current seqno
        seqno = await self.get_seqno()

        # Build external message: treasury wallet sends internal msg to its Jetton wallet
        # Attach enough TON for gas (~0.05 TON)
        query = self._get_wallet().create_transfer_message(
            to_addr=jetton_wallet_addr,
            amount=to_nano(0.05, "ton"),
            seqno=seqno,
            payload=body,
        )

        # Serialize and send
        boc = bytes_to_b64str(query["message"].to_boc(False))
        result = await self._api_post("sendBoc", {"boc": boc})

        msg_hash = result.get("hash", result.get("message_hash", "unknown"))
        logger.info(f"Jetton transfer sent: {msg_hash}")
        return msg_hash

    async def get_pal_balance(self) -> float:
        """Query treasury's PAL token balance."""
        try:
            jetton_wallet_addr = await self.get_jetton_wallet_address(self.treasury_address)
            result = await self._api_post("runGetMethod", {
                "address": jetton_wallet_addr,
                "method": "get_wallet_data",
                "stack": [],
            })
            stack = result.get("stack", [])
            if stack:
                raw_balance = int(stack[0][1], 16) if isinstance(stack[0][1], str) else int(stack[0][1])
                return raw_balance / (10 ** self.pal_decimals)
        except Exception as e:
            logger.error(f"Failed to get PAL balance: {e}")
        return 0.0

    async def get_ton_balance(self) -> float:
        """Query treasury's TON balance for gas."""
        try:
            result = await self._api_get("getAddressBalance", {
                "address": self.treasury_address
            })
            return int(result) / 1_000_000_000
        except Exception as e:
            logger.error(f"Failed to get TON balance: {e}")
            return 0.0
