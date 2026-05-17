"""TON Jetton transfer logic for PAL token distribution."""

import base64
import logging
import time
from typing import Optional

import aiohttp
from pytoniq_core.boc import Builder, Cell
from pytoniq_core.boc.address import Address
from pytoniq_core.crypto.keys import mnemonic_to_wallet_key
from pytoniq_core.crypto.signature import sign_message
from pytoniq import Address as PyAddr
from pytoniq.contract.wallets.wallet_v5 import WalletV5R1, WalletV5WalletID, WALLET_V5_R1_CODE
from pytoniq_core import ExternalMsgInfo, MessageAny
from pytoniq_core.tlb.account import StateInit

logger = logging.getLogger(__name__)

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
        if self._priv_k is None:
            self._pub_k, self._priv_k = mnemonic_to_wallet_key(self.treasury_mnemonic)
            self._wallet_id = WalletV5WalletID(network_global_id=-239, workchain=0).pack()
        return self._pub_k, self._priv_k, self._wallet_id

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

    def _address_to_slice_b64(self, address: str) -> str:
        cell = Builder().store_address(Address(address)).end_cell()
        return base64.b64encode(cell.to_boc()).decode()

    def _parse_address_from_cell(self, cell_b64: str) -> str:
        cell = Cell.one_from_boc(base64.b64decode(cell_b64))
        addr = cell.begin_parse().load_address()
        return addr.to_str(is_user_friendly=True, is_url_safe=True, is_bounceable=True)

    async def get_jetton_wallet_address(self, owner_address: str) -> str:
        result = await self._api_post("runGetMethod", {
            "address": self.jetton_master_address,
            "method": "get_wallet_address",
            "stack": [["tvm.Slice", self._address_to_slice_b64(owner_address)]],
        })
        stack = result.get("stack", [])
        if stack:
            addr_cell_b64 = stack[0][1].get("bytes", "") if isinstance(stack[0][1], dict) else stack[0][1]
            return self._parse_address_from_cell(addr_cell_b64)
        raise RuntimeError("Could not determine Jetton wallet address")

    def _build_jetton_transfer_body(self, to_address: str, amount_raw: int, response_address: str,
                                     query_id: int = 0, forward_ton_amount: int = 1) -> Cell:
        return (
            Builder()
            .store_uint(JETTON_TRANSFER_OP, 32)
            .store_uint(query_id, 64)
            .store_coins(amount_raw)
            .store_address(Address(to_address))
            .store_address(Address(response_address))
            .store_bit(0)
            .store_coins(forward_ton_amount)
            .store_bit(0)
            .end_cell()
        )

    async def get_seqno(self) -> int:
        result = await self._api_post("runGetMethod", {
            "address": self.treasury_address,
            "method": "seqno",
            "stack": [],
        })
        if result.get("exit_code", 0) != 0:
            logger.warning(f"seqno exit_code={result.get('exit_code')} — wallet likely uninitialized")
            return 0
        stack = result.get("stack", [])
        if stack:
            return int(stack[0][1], 16) if isinstance(stack[0][1], str) else int(stack[0][1])
        return 0

    async def send_pal_tokens(self, to_address: str, amount: float) -> str:
        """Execute a PAL Jetton transfer from treasury to recipient."""
        pub_k, priv_k, wallet_id = self._get_signing_params()

        amount_raw = int(amount * (10 ** self.pal_decimals))
        jetton_wallet_addr = await self.get_jetton_wallet_address(self.treasury_address)
        logger.info(f"Treasury Jetton wallet: {jetton_wallet_addr}")

        jetton_body = self._build_jetton_transfer_body(
            to_address=to_address,
            amount_raw=amount_raw,
            response_address=self.treasury_address,
        )

        seqno = await self.get_seqno()

        internal_msg = WalletV5R1.create_wallet_internal_message(
            destination=PyAddr(jetton_wallet_addr),
            send_mode=3,
            value=int(0.05 * 1e9),
            body=jetton_body,
        )

        signing_msg = (
            Builder()
            .store_uint(0x7369676e, 32)
            .store_uint(wallet_id, 32)
            .store_uint(2**32 - 1 if seqno == 0 else int(time.time()) + 120, 32)
            .store_uint(seqno, 32)
            .store_cell(WalletV5R1.pack_actions([internal_msg]))
            .end_cell()
        )

        signature = sign_message(signing_msg.hash, priv_k)
        body_cell = Builder().store_cell(signing_msg).store_bytes(signature).end_cell()

        if seqno == 0:
            state_init = StateInit(
                code=WALLET_V5_R1_CODE,
                data=WalletV5R1.create_data_cell(public_key=pub_k, wallet_id=wallet_id),
            )
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
        try:
            result = await self._api_get("getAddressBalance", {"address": self.treasury_address})
            return int(result) / 1_000_000_000
        except Exception as e:
            logger.error(f"Failed to get TON balance: {e}")
            return 0.0
