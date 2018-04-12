'''
    Masternode
    These are the entry points to the blockchain and pass messages on throughout the system. They are also the cold
    storage points for the blockchain once consumption is done by the network.

    They have no say as to what is 'right,' as governance is ultimately up to the network. However, they can monitor
    the behavior of nodes and tell the network who is misbehaving.
'''
from cilantro import Constants
from cilantro.nodes import NodeBase
from cilantro.protocol.statemachine import State, recv, recv_req, timeout
from cilantro.messages import BlockContender, Envelope, TransactionBase, BlockDataRequest, BlockDataReply
from cilantro.utils import TestNetURLHelper
from aiohttp import web
import asyncio

from cilantro.protocol.structures import MerkleTree
import hashlib

class MNBaseState(State):
    def enter(self, prev_state): pass
    def exit(self, next_state): pass
    def run(self): pass

    @recv(TransactionBase)
    def recv_tx(self, tx: TransactionBase):
        self.log.critical("mn about to pub")
        self.parent.reactor.pub(url=TestNetURLHelper.pubsub_url(self.parent.url), data=Envelope.create(tx))
        self.log.critical("published on our url: {}".format(TestNetURLHelper.pubsub_url(self.parent.url)))
        return web.Response(text="Successfully published transaction: {}".format(tx))

    @recv_req(BlockContender)
    def recv_block(self, block: BlockContender, id):
        self.log.warning("Current state not configured to handle block contender: {}".format(block))

    async def process_request(self, request):
        self.log.warning("Current state not configured to process POST request {}".format(request))


class MNBootState(MNBaseState):
    def enter(self, prev_state):
        self.log.critical("MN URL: {}".format(self.parent.url))
        self.parent.reactor.add_pub(url=TestNetURLHelper.pubsub_url(self.parent.url))
        self.parent.reactor.add_router(url=TestNetURLHelper.dealroute_url(self.parent.url))

    def run(self):
        self.parent.transition(MNRunState)

    def exit(self, next_state):
        self.parent.reactor.notify_ready()

    @recv(TransactionBase)
    def recv_tx(self, tx: TransactionBase):
        self.log.warning("MN BootState not configured to recv transactions")


class MNRunState(MNBaseState):
    NODE_AVAILABLE, NODE_AWAITING, NODE_TIMEOUT = range(3)

    def __init__(self, state_machine=None):
        super().__init__(state_machine=state_machine)
        self.app = web.Application()
        self.loop = asyncio.new_event_loop()
        self.app.router.add_post('/', self.parent.route_http)

        self.block_contenders = []
        self.node_states = {}
        self.tx_hashes = []
        self.retrieved_txs = {}
        self.is_updating = False

    def enter(self, prev_state):
        asyncio.set_event_loop(self.loop)
        # ^ should this just be in init?

    def run(self):
        self.log.info("Starting web server")
        web.run_app(self.app, host=Constants.Testnet.Masternode.Host,
                    port=int(Constants.Testnet.Masternode.ExternalPort))
        # ^ this blocks I think? Or maybe not cause he's on a new event loop..?

    def exit(self, next_state):
        pass
        # TODO -- reset state vars (node_states, transactions, ect)
        # TODO -- stop web server, event loop
        # Or is it blocking? ...
        # And if its blocking that means we can't receive on ZMQ sockets right?

    @recv_req(BlockContender)
    def recv_block(self, block: BlockContender, id):
        self.log.info("Masternode received block contender: {}".format(block))
        self.log.critical("block nodes: {}".format(block.nodes))
        self.block_contenders.append(block)

        if self.is_updating:
            self.log.info("Masternode already executing new block update procedure")
            return

        self.is_updating = True
        self.log.critical("Masternode performing new block update procedure")

        # Compute hash of nodes, validate signatures
        hash_of_nodes = self.compute_hash_of_nodes(block.nodes)
        if not self.validate_sigs(block.signatures, hash_of_nodes):
            self.log.error("MN COULD NOT VALIDATE SIGNATURES FOR CONTENDER {}".format(block))
            # TODO -- remove this block from the queue and try the next (if any available)
            return

        for sig in block.signatures:
            self.node_states[sig.sender] = self.NODE_AVAILABLE
            self.parent.reactor.add_dealer(url=TestNetURLHelper.dealroute_url(sig.sender), id=self.parent.url)
            import time
            time.sleep(0.2)

        self.tx_hashes = block.nodes[len(block.nodes) // 2:]
        repliers = list(self.node_states.keys())

        self.log.critical("block nodes: {}".format(block.nodes))

        for i in range(len(self.tx_hashes)):
            tx = self.tx_hashes[i]
            replier = repliers[i % len(repliers)]
            req = BlockDataRequest.create(tx)
            self.log.critical("Requesting tx hash {} from URL {}".format(tx, replier))
            self.parent.reactor.request(url=TestNetURLHelper.dealroute_url(replier), data=Envelope.create(req), timeout=1)
    #
    # @recv(BlockDataReply)
    # def recv_block_reply(self, reply: BlockDataReply):
    #     self.log.critical("Masternode got block data reply {}".format(reply))
    #     # TODO -- add this to completed transactions, mark sender as available (how?)

    def compute_hash_of_nodes(self, nodes) -> str:
        self.log.critical("Masternode computing hash of nodes...")
        h = hashlib.sha3_256()
        [h.update(o) for o in nodes]
        hash_of_nodes = h.digest()
        self.log.critical("Masternode got hash of nodes: {}".format(hash_of_nodes))
        return hash_of_nodes

    def validate_sigs(self, signatures, msg) -> bool:
        for sig in signatures:
            self.log.info("mn verifying signature: {}".format(sig))
            sender_vk = Constants.Testnet.AllNodes[sig.sender]
            if sig.verify(msg, Constants.Testnet.AllNodes[sig.sender]):
                self.log.critical("Good we verified that sig")
            else:
                self.log.error("!!!! Oh no why couldnt we verify sig {}???".format(sig))
                return False
        return True

    @recv(BlockDataReply)
    def recv_blockdata_reply(self, reply: BlockDataReply):
        if not self.is_updating:
            self.log.error("Received block data reply but not in updating state (reply={})".format(reply))
            return

        self.log.critical("masternode got block data reply: {}".format(reply))
        tx_hash = reply.tx_hash
        self.log.critical("BlockReply tx hash: {}".format(tx_hash))
        self.log.critical("Pending transactions: {}".format(self.tx_hashes))
        if tx_hash in self.tx_hashes:
            self.retrieved_txs[tx_hash] = reply.raw_tx
        else:
            self.log.error("Received block data reply with tx hash {} that is not in tx_hashes")

        if len(self.retrieved_txs) == len(self.tx_hashes):
            self.log.critical("\n***\nDONE COLLECTING BLOCK DATA FROM NODES\n***\n")
        else:
            self.log.critical("Still {} transactions yet to request until we can build the block"
                              .format(len(self.tx_hashes) - len(self.retrieved_txs)))

    @timeout(BlockDataRequest)
    def timeout_block_req(self, request: BlockDataRequest, url):
        self.log.critical("BlockDataRequest timed out for url {} with request data {}".format(url, request))
        pass

class MNNewBlockState(MNBaseState): pass


class Masternode(NodeBase):
    _INIT_STATE = MNBootState
    _STATES = [MNBootState, MNRunState]
    def __init__(self, url=Constants.Testnet.Masternode.InternalUrl, signing_key=Constants.Testnet.Masternode.Sk):
        super().__init__(url=url, signing_key=signing_key)
        self.start()