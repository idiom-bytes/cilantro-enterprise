import zmq.asyncio
import asyncio

from cilantro_ee.services.storage.state import MetaDataStorage
from cilantro_ee.services.storage.master import CilantroStorageDriver
from cilantro_ee.services.storage.vkbook import VKBook

from cilantro_ee.core.crypto.wallet import Wallet
from cilantro_ee.core.messages.message_type import MessageType
from cilantro_ee.core.messages.message import Message

from cilantro_ee.services.overlay.network import NetworkParameters, ServiceType
from cilantro_ee.core.sockets.socket_book import SocketBook
from cilantro_ee.core.sockets.services import SubscriptionService
from cilantro_ee.services.block_fetch import BlockFetcher
from cilantro_ee.core.utils.block_sub_block_mapper import BlockSubBlockMapper

from cilantro_ee.nodes.masternode.block_aggregator import BlockAggregator, BNKind


class BlockNotificationForwarder(SubscriptionService):
    def __init__(self, socket_base, ctx: zmq.asyncio.Context, wallet, network_parameters, contacts: VKBook,
                 driver: CilantroStorageDriver, state=MetaDataStorage()):
        self.socket_base = socket_base,
        self.wallet = wallet
        self.network_parameters = network_parameters
        self.contacts = contacts
        self.state = state
        self.driver = driver

        self.fetcher = BlockFetcher(wallet=self.wallet,
                                    ctx=self.ctx,
                                    blocks=self.driver,
                                    state=self.state,
                                    contacts=self.contacts,
                                    network_parameters=self.network_parameters)

        self.masternode_sockets = SocketBook(socket_base=self.socket_base,
                                             service_type=ServiceType.BLOCK_AGGREGATOR,
                                             ctx=self.ctx,
                                             network_parameters=self.network_parameters,
                                             phonebook_function=self.contacts.contract.get_masternodes)

        super().__init__(ctx=ctx)

    async def start(self):
        await self.connect_to_peer_masternodes()
        asyncio.ensure_future(self.serve)

        while self.running:
            if len(self.received) > 0:
                msg, addr = self.received.pop(0)
                await self.forward_new_block_notifications(addr, msg)

    async def connect_to_peer_masternodes(self):
        await self.masternode_sockets.refresh()
        del self.masternode_sockets.sockets[self.wallet.verifying_key().hex()]

        for masternode in self.masternode_sockets.sockets.values():
            self.add_subscription(masternode)

    async def forward_new_block_notifications(self, sender, msg):
        blocknum = msg.blockNum

        if (blocknum > self.state.latest_block_num + 1) and \
                (msg.type.which() == "newBlock"):
            await self.fetcher.intermediate_sync(msg)


# Create socket base
class BlockAggregatorController:
    def __init__(self,
                 wallet,
                 socket_base,
                 vkbook,
                 ctx: zmq.asyncio.Context,
                 network_parameters=NetworkParameters(),
                 state: MetaDataStorage=MetaDataStorage(),
                 block_timeout=60*1000):

        self.wallet = wallet
        self.vkbook = vkbook
        self.ctx = ctx
        self.network_parameters = network_parameters

        self.delegate_sockets = SocketBook(socket_base=socket_base,
                                           service_type=ServiceType.SUBBLOCK_BUILDER_PUBLISHER,
                                           ctx=self.ctx,
                                           network_parameters=self.network_parameters,
                                           phonebook_function=self.vkbook.contract.get_delegates)

        self.driver = CilantroStorageDriver(key=self.wallet.signing_key(), vkbook=self.vkbook)

        self.state = state

        self.min_quorum = self.vkbook.delegate_quorum_min
        self.max_quorum = self.vkbook.delegate_quorum_max

        block_sb_mapper = BlockSubBlockMapper(self.vkbook.masternodes)
        my_vk = self.wallet.verifying_key()

        sb_nums = block_sb_mapper.get_list_of_sb_numbers(my_vk)

        self.sb_numbers = sb_nums
        self.sb_indices = block_sb_mapper.get_set_of_sb_indices(sb_nums)

        # Modify block agg to take an async inbox instead
        self.aggregator = BlockAggregator(subscription=None,
                                          block_timeout=block_timeout,
                                          min_quorum=self.min_quorum,
                                          max_quorum=self.max_quorum,
                                          current_quorum=self.max_quorum,
                                          contacts=self.vkbook)

        # Setup publisher socket for other masternodes to subscribe to
        self.pub_socket_address = self.network_parameters.resolve(socket_base=socket_base,
                                                                  service_type=ServiceType.BLOCK_AGGREGATOR,
                                                                  bind=True)
        self.pub_socket = self.ctx.socket(zmq.PUB)
        self.pub_socket.bind(str(self.pub_socket_address))

        self.running = False

    async def start(self):
        await self.start_aggregator()
        self.running = True
        asyncio.ensure_future(self.process_blocks())

        # await self.informer.send_ready()
        await self.send_ready()

    async def start_aggregator(self):
        # Initialize a Subscription for the Delegate Block Builders
        subscription = SubscriptionService(ctx=self.ctx)
        current_quorum = 0

        # Refresh the sockets for the delegate block builders
        await self.delegate_sockets.refresh()

        # Connect to each delegate we have and note the quorum
        for delegate in self.delegate_sockets.sockets.values():
            subscription.add_subscription(delegate)
            current_quorum += 1

        # Set the subscription and quorum on the aggregator
        self.aggregator.subblock_subscription_service = subscription
        self.aggregator.current_quorum = current_quorum

        # Start the subscription service
        asyncio.ensure_future(self.aggregator.subblock_subscription_service.serve())

    async def process_blocks(self):
        while self.running:
            block, kind = await self.aggregator.gather_block()

            # Burn input hashes if needed
            if len(block) > 0:
                await self.informer.send_burn_input_hashes(
                    hashes=self.get_input_hashes_to_burn(block)
                )

                notification = self.driver.get_block_dict(block, kind)

                del notification['prevBlockHash']
                del notification['subBlocks']

                owners = []
                if kind == BNKind.NEW:
                    self.driver.store_block(sub_blocks=block)
                    owners = [m for m in self.vkbook.masternodes]
                    notification['newBlock'] = None

                notification['blockOwners'] = owners

                if kind == BNKind.SKIP:
                    notification['emptyBlock'] = None

                if kind == BNKind.FAIL:
                    notification['failedBlock'] = None

                block_notification = Message.get_signed_message_packed_2(
                    wallet=self.wallet,
                    msg_type=MessageType.BLOCK_NOTIFICATION,
                    **notification
                )

                await self.pub_socket.send(block_notification)

    async def process_block(self):
        block, kind = await self.aggregator.gather_block()

        # Burn input hashes if needed
        if len(block) > 0:
            await self.informer.send_burn_input_hashes(
                hashes=self.get_input_hashes_to_burn(block)
            )

            notification = self.driver.get_block_dict(block, kind)

            del notification['prevBlockHash']
            del notification['subBlocks']

            owners = []
            if kind == BNKind.NEW:
                self.driver.store_block(sub_blocks=block)
                owners = [m for m in self.vkbook.masternodes]
                notification['newBlock'] = None

            notification['blockOwners'] = owners

            if kind == BNKind.SKIP:
                notification['emptyBlock'] = None

            if kind == BNKind.FAIL:
                notification['failedBlock'] = None

            block_notification = Message.get_signed_message_packed_2(
                wallet=self.wallet,
                msg_type=MessageType.BLOCK_NOTIFICATION,
                **notification
            )

            await self.pub_socket.send(block_notification)


    def stop(self):
        # Order matters here
        self.running = False
        self.aggregator.running = False
        self.aggregator.pending_block.started = True
        self.aggregator.subblock_subscription_service.stop()
