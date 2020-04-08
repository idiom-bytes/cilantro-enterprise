from cilantro_ee.messages.message import Message
from cilantro_ee.messages.message_type import MessageType
from cilantro_ee.crypto.wallet import Wallet, _verify
import hashlib
from .transaction import transaction_is_valid, TransactionException
from cilantro_ee.messages import schemas

import capnp
import os
import time

transaction_capnp = capnp.load(os.path.dirname(schemas.__file__) + '/transaction.capnp')

# struct TransactionBatch {
#     transactions @0 :List(NewTransaction);
#     timestamp @1: Float64;
#     signature @2: Data;
#     sender @3: Data;
#     inputHash @4: Text;  # hash of transactions + timestamp
# }


class TXBatchInvalidError(Exception):
    pass


class NotTransactionBatchMessageType(TXBatchInvalidError):
    pass


class ReceivedInvalidWork(TXBatchInvalidError):
    pass


class InvalidSignature(TXBatchInvalidError):
    pass


class NotMasternode(TXBatchInvalidError):
    pass


def make_shim_tx_batch(sender, timestamp):
    return transaction_capnp.TransactionBatch.new_message(
        transactions=[],
        timestamp=timestamp,
        signature=b'\x00' * 64,
        inputHash=sender,
        sender=sender
    )

def transaction_list_to_transaction_batch(tx_list, wallet: Wallet):
    h = hashlib.sha3_256()
    for tx in tx_list:
        # Hash it
        tx_bytes = tx.to_bytes_packed()
        h.update(tx_bytes)
    # Add a timestamp
    timestamp = time.time()
    h.update('{}'.format(timestamp).encode())
    input_hash = h.digest().hex()

    signature = wallet.sign(bytes.fromhex(input_hash))

    msg = Message.get_message(
        msg_type=MessageType.TRANSACTION_BATCH,
        transactions=[t for t in tx_list],
        timestamp=timestamp,
        signature=signature,
        inputHash=input_hash,
        sender=wallet.verifying_key()
    )

    return msg[1]


def tx_batch_is_valid(tx_batch, masternodes, latest_block_hash, latest_block_num, timeout=1000):
    if tx_batch.sender.hex() not in masternodes:
        raise NotMasternode

    # Set up a hasher for input hash and a list for valid txs
    h = hashlib.sha3_256()

    for tx in tx_batch.transactions:
        # Double check to make sure all transactions are valid
        try:
            transaction_is_valid(tx=tx,
                                 expected_processor=tx_batch.sender,
                                 driver=self.nonces,
                                 strict=False)
        except TransactionException as e:
            raise e

        h.update(tx.as_builder().to_bytes_packed())

    h.update('{}'.format(tx_batch.timestamp).encode())
    input_hash = h.digest()
    if input_hash != tx_batch.inputHash or \
            not _verify(tx_batch.sender, h.digest(), tx_batch.signature):
        raise InvalidSignature


