from cilantro_ee.crypto.wallet import Wallet
from cilantro_ee.crypto import transaction
from contracting.db.driver import ContractDriver, InMemDriver
from cilantro_ee import storage
from cilantro_ee.nodes import masternode, delegate
import asyncio
import random
import httpx
from cilantro_ee.logger.base import get_logger


class MockNode:
    def __init__(self, ctx, index=1):
        self.wallet = Wallet()
        port = 18000 + index
        self.ip = f'tcp://127.0.0.1:{port}'
        self.driver = ContractDriver(driver=InMemDriver())
        self.ctx = ctx

        self.bootnodes = {}
        self.constitution = {}
        self.ready_to_start = False
        self.started = False

        self.obj = None

    def set_start_variables(self, bootnodes, constitution):
        self.bootnodes = bootnodes
        self.constitution = constitution
        self.ready_to_start = True

    def flush(self):
        self.driver.flush()


class MockMaster(MockNode):
    def __init__(self, ctx, index=1):
        super().__init__(ctx, index)

        self.webserver_port = 18080 + index
        self.webserver_ip = f'http://0.0.0.0:{self.webserver_port}'

        self.blocks = storage.BlockStorage(db=f'blockchain-{index}')

    async def start(self):
        assert self.ready_to_start, 'Not ready to start!'

        self.obj = masternode.Masternode(
            socket_base=self.ip,
            ctx=self.ctx,
            wallet=self.wallet,
            constitution=self.constitution,
            bootnodes=self.bootnodes,
            blocks=self.blocks,
            driver=self.driver,
            webserver_port=self.webserver_port
        )

        await self.obj.start()
        self.started = True

    def flush(self):
        super().flush()
        self.blocks.drop_collections()

    def stop(self):
        self.obj.stop()


class MockDelegate(MockNode):
    def __init__(self, ctx, index=1):
        super().__init__(ctx, index)

    async def start(self):
        assert self.ready_to_start, 'Not ready to start!'

        self.obj = delegate.Delegate(
            socket_base=self.ip,
            ctx=self.ctx,
            wallet=self.wallet,
            constitution=self.constitution,
            bootnodes=self.bootnodes,
            driver=self.driver,
        )

        await self.obj.start()
        self.started = True

    def stop(self):
        self.obj.stop()


class MockNetwork:
    def __init__(self, num_of_masternodes, num_of_delegates, ctx):
        self.masternodes = []
        self.delegates = []

        self.log = get_logger('MOCKNET')

        self.ctx = ctx

        for i in range(0, num_of_masternodes):
            self.build_masternode(i)

        for i in range(num_of_masternodes, num_of_delegates + num_of_masternodes):
            self.build_delegate(i)

        self.constitution = None
        self.bootnodes = None

        self.prepare_nodes_to_start()

    def prepare_nodes_to_start(self):
        constitution = {
            'masternodes': [],
            'delegates': []
        }

        bootnodes = dict()

        for m in self.masternodes:
            constitution['masternodes'].append(m.wallet.verifying_key)
            bootnodes[m.wallet.verifying_key] = m.ip

        for d in self.delegates:
            constitution['delegates'].append(d.wallet.verifying_key)
            bootnodes[d.wallet.verifying_key] = d.ip

        for node in self.masternodes + self.delegates:
            node.set_start_variables(bootnodes=bootnodes, constitution=constitution)

        self.constitution = constitution
        self.bootnodes = bootnodes

    def build_delegate(self, index):
        self.delegates.append(MockDelegate(self.ctx, index))

    def build_masternode(self, index):
        self.masternodes.append(MockMaster(self.ctx, index=index))

    def fund(self, vk, min_balance=50000):
        current_balance = self.masternodes[0].driver.get_var(
            contract='currency',
            variable='balances',
            arguments=[vk]
        )

        if current_balance is None:
            current_balance = 0

        if current_balance < min_balance:
            new_balance = current_balance + min_balance
            self.set_var(
                contract='currency',
                variable='balances',
                arguments=[vk],
                value=new_balance
            )

    def get_var(self, contract, variable, arguments, delegates=False):
        true_value = None
        for master in self.masternodes:
            value = master.driver.get_var(
                contract=contract,
                variable=variable,
                arguments=arguments
            )
            if true_value is None:
                true_value = value
            else:
                assert true_value == value, 'Masters have inconsistent state!'

        if delegates:
            for delegate in self.delegates:
                value = delegate.driver.get_var(
                    contract=contract,
                    variable=variable,
                    arguments=arguments
                )
                if true_value is None:
                    true_value = value
                else:
                    assert true_value == value, 'Masters have inconsistent state!'

        return true_value

    def set_var(self, contract, variable, arguments, value):
        for node in self.masternodes + self.delegates:
            assert node.started, 'All nodes must be started first to mint.'

            node.driver.set_var(
                contract=contract,
                variable=variable,
                arguments=arguments,
                value=value
            )

    async def start(self):
        coroutines = [node.start() for node in self.masternodes + self.delegates]

        await asyncio.gather(
            *coroutines
        )

    def stop(self):
        for node in self.masternodes + self.delegates:
            node.stop()

    async def make_and_push_tx(self, wallet, contract, function, kwargs={}, stamps=1_000_000, mn_idx=0, random_select=False):
        # Mint money if we have to
        self.fund(wallet.verifying_key)

        # Get our node we are going to send the tx to
        if random_select:
            node = random.choice(self.masternodes)
        else:
            node = self.masternodes[mn_idx]

        processor = node.wallet.verifying_key

        async with httpx.AsyncClient() as client:
            response = await client.get(f'{node.webserver_ip}/nonce/{wallet.verifying_key}')
            nonce = response.json()['nonce']

        self.log.info(f'Nonce is {nonce}')

        tx = transaction.build_transaction(
            wallet=wallet,
            contract=contract,
            function=function,
            kwargs=kwargs,
            stamps=stamps,
            processor=processor,
            nonce=nonce
        )

        async with httpx.AsyncClient() as client:
            await client.post(f'{node.webserver_ip}/', data=tx)

    def flush(self):
        for node in self.masternodes + self.delegates:
            node.flush()

    def refresh(self):
        self.flush()
        for node in self.masternodes + self.delegates:
            node.obj.seed_genesis_contracts()