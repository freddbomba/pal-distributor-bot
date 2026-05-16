"""TON Jetton transfer logic for PAL token distribution."""

import base64
import logging
import time
from typing import Optional

import aiohttp
from tonsdk.boc import Cell, begin_cell
from tonsdk.utils import bytes_to_b64str, Address

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
        self._pub_k = None
        self._priv_k = None
        self._wallet_id = None

    def _get_signing_params(self):
        """Lazily derive W5R1 key pair and wallet_id from mnemonic."""
        if self._priv_k is None:
            from pytoniq_core.crypto.keys import mnemonic_to_wallet_key
            from pytoniq.contract.wallets.wallet_v5 import WalletV5WalletID
            self._pub_k, self._priv_k = mnemonic_to_wallet_key(self.treasury_mnemonic)
            self._wallet_id = WalletV5WalletID(network_global_id=-239, workchain=0).pack()
        return self._priv_k, self._wallet_id

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
        stack = result.get("stack", [])
        if stack and len(stack) > 0:
            addr_cell_b64 = stack[0][1].get("bytes", "") if isinstance(stack[0][1], dict) else stack[0][1]
            return self._parse_address_from_cell(addr_cell_b64)
        raise RuntimeError("Could not determine Jetton wallet address")

    def _address_to_slice_b64(self, address: str) -> str:
        addr = Address(address)
        cell = begin_cell().store_address(addr).end_cell()
        return bytes_to_b64str(cell.to_boc())

    def _parse_address_from_cell(self, cell_b64: str) -> str:
        boc_bytes = base64.b64decode(cell_b64)
        cell = Cell.one_from_boc(boc_bytes)
        cs = cell.begin_parse()
        addr = cs.read_msg_addr()
        return addr.to_string(True, True, True)

    def _build_jetton_transfer_body(
        self,
        to_address: str,
        amount_raw: int,
        response_address: str,
        query_id: int = 0,
        forward_ton_amount: int = 1,
    ) -> Cell:
        dest_addr = Address(to_address)
        resp_addr = Address(response_address)
        return (
            begin_cell()
            .store_uint(JETTON_TRANSFER_OP, 32)
            .store_uint(query_id, 64)
            .store_coins(amount_raw)
            .store_address(dest_addr)
            .store_address(resp_addr)
            .store_bit(0)
            .store_coins(forward_ton_amount)
            .store_bit(0)
            .end_cell()
        )

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
        """Execute a PAL Jetton transfer from treasury to recipient."""
        from pytoniq.contract.wallets.wallet_v5 import WalletV5R1, sign_message, WALLET_V5_R1_CODE
        from pytoniq_core import Address as PyAddr, ExternalMsgInfo, MessageAny, Builder as PBuilder, Cell as PCell
        from pytoniq_core.tlb.account import StateInit

        priv_k, wallet_id = self._get_signing_params()

        amount_raw = int(amount * (10 ** self.pal_decimals))

        jetton_wallet_addr = await self.get_jetton_wallet_address(self.treasury_address)
        logger.info(f"Treasury Jetton wallet: {jetton_wallet_addr}")

        # Build Jetton body with tonsdk, convert to pytoniq Cell via BOC
        body_tonsdk = self._build_jetton_transfer_body(
            to_address=to_address,
            amount_raw=amount_raw,
            response_address=self.treasury_address,
        )
        body_pytoniq = PCell.one_from_boc(bytes(body_tonsdk.to_boc(False)))

        seqno = await self.get_seqno()

        # Build W5R1 internal message (treasury → its Jetton wallet)
        internal_msg = WalletV5R1.create_wallet_internal_message(
            destination=PyAddr(jetton_wallet_addr),
            send_mode=3,
            value=int(0.05 * 1e9),  # 0.05 TON for gas
            body=body_pytoniq,
        )

        # Build W5R1 signed message body
        signing_msg = PBuilder().store_uint(0x7369676e, 32)  # signed external op
        signing_msg.store_uint(wallet_id, 32)
        if seqno == 0:
            signing_msg.store_uint(2**32 - 1, 32)
        else:
            signing_msg.store_uint(int(time.time()) + 120, 32)  # valid_until
        signing_msg.store_uint(seqno, 32)
        signing_msg.store_cell(WalletV5R1.pack_actions([internal_msg]))
        signing_msg_cell = signing_msg.end_cell()

        signature = sign_message(signing_msg_cell.hash, priv_k)
        # W5R1: signature (512 bits) must come first, then the signed body
        body_cell = PBuilder().store_bytes(signature).store_cell(signing_msg_cell).end_cell()

        # Wrap in external message and serialize to BOC
        # When seqno == 0 the wallet contract hasn't been deployed yet.
        # We must include a StateInit (code + data) so the blockchain
        # deploys the W5R1 smart contract on the first outgoing message.
        if seqno == 0:
            data_cell = WalletV5R1.create_data_cell(
                public_key=self._pub_k,
                wallet_id=wallet_id,
            )
            state_init = StateInit(code=WALLET_V5_R1_CODE, data=data_cell)
            logger.info("First transaction — including StateInit to deploy wallet")
        else:
            state_init = None

        ext_msg = MessageAny(
            info=ExternalMsgInfo(src=None, dest=PyAddr(self.treasury_address), import_fee=0),
            init=state_init,
            body=body_cell,
        )
        boc_b64 = base64.b64encode(ext_msg.serialize().to_boc()).decode()

        result = await self._api_post("sendBoc", {"boc": boc_b64})
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
