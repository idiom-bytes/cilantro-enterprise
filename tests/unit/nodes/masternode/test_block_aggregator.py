from cilantro.logger.base import get_logger
from cilantro.constants.testnet import TESTNET_MASTERNODES
from cilantro.nodes.masternode.block_aggregator import BlockAggregator
from cilantro.storage.db import VKBook

import unittest
from unittest import TestCase
from unittest import mock
from unittest.mock import MagicMock
from cilantro.constants.zmq_filters import MASTERNODE_DELEGATE_FILTER, MASTER_MASTER_FILTER, DEFAULT_FILTER
from cilantro.constants.ports import MASTER_ROUTER_PORT, MASTER_PUB_PORT, DELEGATE_PUB_PORT, DELEGATE_ROUTER_PORT
from cilantro.messages.envelope.envelope import Envelope
from cilantro.messages.consensus.sub_block_contender import SubBlockContender
from cilantro.messages.consensus.sub_block import SubBlockHashes
from cilantro.messages.consensus.merkle_signature import build_test_merkle_sig
from cilantro.messages.block_data.block_metadata import FullBlockMetaData
from cilantro.constants.delegate import NODES_REQUIRED_CONSENSUS
from cilantro.utils.hasher import Hasher
from cilantro.protocol.structures.merkle_tree import MerkleTree

TEST_IP = '127.0.0.1'
TEST_SK = TESTNET_MASTERNODES[0]['sk']
TEST_VK = TESTNET_MASTERNODES[0]['vk']
INPUT_HASH = b'1111111111111111111111111111111111111111111111111111111111111111'
INPUT_HASH_1 = b'2222222222222222222222222222222222222222222222222222222222222222'
RAWTXS = [
    b'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
    b'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB',
    b'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC',
    b'DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD',
    b'EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE'
]
RAWTXS_1 = [
    b'1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
    b'2BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB',
    b'3CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC',
    b'4DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD',
    b'5EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE'
]
mt = MerkleTree.from_raw_transactions(RAWTXS)
mt_1 = MerkleTree.from_raw_transactions(RAWTXS_1)
MERKLE_LEAVES = mt.leaves
MERKLE_LEAVES_1 = mt_1.leaves
RESULT_HASH = mt.root
RESULT_HASH_1 = mt_1.root

class TestBlockAggregator(TestCase):

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    def test_build_task_list_connect_and_bind(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):
        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)

        mock_manager = MagicMock()
        ba.manager = mock_manager

        mock_pub, mock_sub, mock_server_router, mock_client_router = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        mock_manager.create_socket = MagicMock(side_effect=[mock_sub, mock_pub, mock_server_router, mock_client_router])

        mock_sub_handler_task = MagicMock()
        mock_sub.add_handler = MagicMock(return_value=mock_sub_handler_task)

        ba.build_task_list()

        self.assertEqual(ba.sub, mock_sub)
        self.assertEqual(ba.pub, mock_pub)
        mock_sub.add_handler.assert_called()
        self.assertTrue(mock_sub_handler_task in ba.tasks)

        self.assertEqual(mock_sub.connect.call_count,
            len([vk for vk in VKBook.get_masternodes() if TEST_VK != vk]) + \
                len([vk for vk in VKBook.get_delegates() if TEST_VK != vk]))

        mock_pub.bind.assert_called_with(ip=TEST_IP, port=MASTER_PUB_PORT)

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    def test_handle_recv_sub_block_contender(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):

        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)

        ba.manager = MagicMock()
        ba.recv_sub_block_contender = MagicMock()
        ba.build_task_list()

        mock_env = MagicMock()
        mock_env.message = MagicMock(spec=SubBlockContender)

        with mock.patch.object(Envelope, 'from_bytes', return_value=mock_env):
            ba.handle_sub_msg([b'filter doesnt matter', b'envelope binary also doesnt matter'])

        ba.recv_sub_block_contender.assert_called_with(mock_env.message)

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    def test_handle_recv_result_hash(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):

        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)

        ba.manager = MagicMock()
        ba.recv_full_block_hash_metadata = MagicMock()
        ba.build_task_list()

        mock_env = MagicMock()
        mock_env.message = MagicMock(spec=FullBlockMetaData)

        with mock.patch.object(Envelope, 'from_bytes', return_value=mock_env):
            ba.handle_sub_msg([b'filter doesnt matter', b'envelope binary also doesnt matter'])

        ba.recv_full_block_hash_metadata.assert_called_with(mock_env.message)

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    def test_recv_sub_block_contender(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):

        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)

        ba.manager = MagicMock()
        ba.build_task_list()

        signature = build_test_merkle_sig()
        sbc = SubBlockContender.create(RESULT_HASH, INPUT_HASH, MERKLE_LEAVES, signature, RAWTXS)

        ba.recv_sub_block_contender(sbc)
        self.assertTrue(sbc._data.signature in ba.result_hashes[RESULT_HASH.hex()]['signatures'])

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    def test_recv_sub_block_contender_fail(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):

        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)

        ba.manager = MagicMock()
        ba.build_task_list()

        signature = build_test_merkle_sig()
        sbc = SubBlockContender.create(RESULT_HASH, INPUT_HASH, MERKLE_LEAVES, signature, RAWTXS)

        sbc._data.resultHash = b'A' * 63

        with self.assertRaises(AssertionError):
            ba.recv_sub_block_contender(sbc)

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    def test_combine_result_hash(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):

        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)

        ba.manager = MagicMock()
        ba.build_task_list()
        ba.pub = MagicMock()
        ba.pub.send_msg = MagicMock()
        bh = ba.curr_block_hash

        for i in range(NODES_REQUIRED_CONSENSUS):
            signature = build_test_merkle_sig()
            sbc = SubBlockContender.create(RESULT_HASH, INPUT_HASH, MERKLE_LEAVES, signature, RAWTXS)
            ba.recv_sub_block_contender(sbc)

        ba.curr_block_hash = bh
        sub_block_hashes = sorted(ba.contenders.keys())
        fbmd = ba.construct_full_block(sub_block_hashes)
        ba.pub.send_msg.assert_called_with(msg=fbmd, header=DEFAULT_FILTER.encode())

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    def test_combine_result_hash_transactions_missing(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):

        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)

        ba.manager = MagicMock()
        ba.build_task_list()

        signature = build_test_merkle_sig()
        sbc = SubBlockContender.create(RESULT_HASH, INPUT_HASH, MERKLE_LEAVES, signature, RAWTXS)
        sbc._data.transactions = RAWTXS[:3]
        with self.assertRaises(AssertionError):
            ba.recv_sub_block_contender(sbc)

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.SUBBLOCKS_REQUIRED", 2)
    @mock.patch("cilantro.messages.block_data.block_metadata.SUBBLOCKS_REQUIRED", 2)
    def test_recv_result_hash_multiple_subblocks(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):

        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)
        ba.manager = MagicMock()
        ba.build_task_list()
        bh = ba.curr_block_hash

        # Sub block 0
        for i in range(NODES_REQUIRED_CONSENSUS):
            signature = build_test_merkle_sig()
            sbc = SubBlockContender.create(RESULT_HASH, INPUT_HASH, MERKLE_LEAVES, signature, RAWTXS)
            ba.recv_sub_block_contender(sbc)

        # Sub block 1
        for i in range(NODES_REQUIRED_CONSENSUS):
            signature = build_test_merkle_sig()
            sbc = SubBlockContender.create(RESULT_HASH_1, INPUT_HASH_1, MERKLE_LEAVES_1, signature, RAWTXS_1)
            ba.recv_sub_block_contender(sbc)

        sub_block_hashes = sorted(ba.contenders.keys())
        block_hash = Hasher.hash_iterable([*sub_block_hashes, bh])
        self.assertEqual(ba.full_block_hashes[block_hash]['full_block_metadata'].merkle_roots, sub_block_hashes)
        self.assertEqual(ba.total_valid_sub_blocks, 2)

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.SUBBLOCKS_REQUIRED", 2)
    @mock.patch("cilantro.messages.block_data.block_metadata.SUBBLOCKS_REQUIRED", 2)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.MASTERNODE_REQUIRED_CONSENSUS", 3)
    def test_recv_result_hash_multiple_subblocks_consensus(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):
        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)
        ba.manager = MagicMock()
        ba.build_task_list()
        bh = ba.curr_block_hash

        # Sub block 0
        for i in range(NODES_REQUIRED_CONSENSUS):
            signature = build_test_merkle_sig()
            sbc = SubBlockContender.create(RESULT_HASH, INPUT_HASH, MERKLE_LEAVES, signature, RAWTXS)
            ba.recv_sub_block_contender(sbc)

        # Sub block 1
        for i in range(NODES_REQUIRED_CONSENSUS):
            signature = build_test_merkle_sig()
            sbc = SubBlockContender.create(RESULT_HASH_1, INPUT_HASH_1, MERKLE_LEAVES_1, signature, RAWTXS_1)
            ba.recv_sub_block_contender(sbc)

        self.assertEqual(ba.total_valid_sub_blocks, 2)
        ba.curr_block_hash = bh
        fbmd = ba.construct_full_block(ba.contenders.keys())
        for i in range(3):
            ba.recv_full_block_hash_metadata(fbmd)
        self.assertEqual(ba.full_block_hashes[ba.curr_block_hash]['consensus_count'], 3)
        self.assertEqual(ba.full_block_hashes[ba.curr_block_hash]['full_block_metadata'], fbmd)
        self.assertEqual(ba.total_valid_sub_blocks, 0)

    @mock.patch("cilantro.protocol.multiprocessing.worker.asyncio", autospec=True)
    @mock.patch("cilantro.protocol.multiprocessing.worker.SocketManager", autospec=True)
    @mock.patch("cilantro.nodes.masternode.block_aggregator.BlockAggregator.run", autospec=True)
    def test_recv_ignore_extra_sub_block_contenders(self, mock_run_method, mock_bm_asyncio, mock_worker_asyncio):
        ba = BlockAggregator(ip=TEST_IP, signing_key=TEST_SK)
        ba.manager = MagicMock()
        ba.build_task_list()
        bh = ba.curr_block_hash
        for i in range(NODES_REQUIRED_CONSENSUS + 5):
            signature = build_test_merkle_sig()
            sbc = SubBlockContender.create(RESULT_HASH, INPUT_HASH, MERKLE_LEAVES, signature, RAWTXS)
            ba.recv_sub_block_contender(sbc)

        ba.curr_block_hash = bh
        fbmd = ba.construct_full_block(ba.contenders.keys())
        ba.pub.send_msg.assert_called_with(msg=fbmd, header=DEFAULT_FILTER.encode())

if __name__ == '__main__':
    unittest.main()