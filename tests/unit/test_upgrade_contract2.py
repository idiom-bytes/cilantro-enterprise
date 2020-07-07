import unittest
import os
from cilantro_ee.contracts import sync
from cilantro_ee.upgrade import build_pepper, get_version
from cilantro_ee.crypto.wallet import Wallet
import cilantro_ee
from unittest import TestCase
from contracting.client import ContractingClient


class TestUpdateContractFix(TestCase):
    def setUp(self):
        self.client = ContractingClient()
        self.client.flush()

        self.mn_wallets = [Wallet().verifying_key for _ in range(3)]
        self.dn_wallets = [Wallet().verifying_key for _ in range(3)]

        # Sync contracts
        sync.setup_genesis_contracts(
            initial_masternodes=self.mn_wallets,
            initial_delegates=self.dn_wallets,
            client=self.client,
            filename=cilantro_ee.contracts.__path__[0] + '/genesis.json',
            root=cilantro_ee.contracts.__path__[0]
        )

        with open(cilantro_ee.contracts.__path__[0] + '/genesis/new_upgrade.s.py') as f:
            code = f.read()
            self.client.submit(code, name='new_upgrade')

        self.upgrade = self.client.get_contract('new_upgrade')

    def tearDown(self):
        self.client.flush()

    def test_initial_state(self):
        self.assertEqual(self.upgrade.upgrade_state['locked'], False)
        self.assertEqual(self.upgrade.upgrade_state['has_consensus'], False)

        self.assertEqual(self.upgrade.upgrade_state['votes'], 0)
        self.assertEqual(self.upgrade.upgrade_state['voters'], 0)

    def test_is_valid_voter_true_for_master(self):
        r = self.upgrade.run_private_function(
            f='is_valid_voter',
            address=self.mn_wallets[0]
        )
        self.assertTrue(r)

    def test_is_valid_voter_true_for_delegate(self):
        r = self.upgrade.run_private_function(
            f='is_valid_voter',
            address=self.dn_wallets[0]
        )
        self.assertTrue(r)

    def test_is_valid_voter_false_for_others(self):
        r = self.upgrade.run_private_function(
            f='is_valid_voter',
            address=Wallet().verifying_key
        )
        self.assertFalse(r)

    def test_start_vote_sets_state(self):
        self.upgrade.run_private_function(
            f='start_vote',
            cilantro_branch_name='hello1',
            contracting_branch_name='hello2',
            pepper='123xyz'
        )

        self.assertEqual(self.upgrade.upgrade_state['locked'], True)
        self.assertEqual(self.upgrade.upgrade_state['has_consensus'], False)

        self.assertEqual(self.upgrade.upgrade_state['votes'], 0)
        self.assertEqual(self.upgrade.upgrade_state['voters'], 6)

        self.assertEqual(self.upgrade.upgrade_state['pepper'], '123xyz')
        self.assertEqual(self.upgrade.upgrade_state['cilantro_branch_name'], 'hello1')
        self.assertEqual(self.upgrade.upgrade_state['contracting_branch_name'], 'hello2')

    def test_first_vote_starts_vote(self):
        self.upgrade.vote(
            signer=self.mn_wallets[0],
            cilantro_branch_name='hello1',
            contracting_branch_name='hello2',
            pepper='123xyz'
        )

        self.assertEqual(self.upgrade.upgrade_state['locked'], True)
        self.assertEqual(self.upgrade.upgrade_state['has_consensus'], False)

        self.assertEqual(self.upgrade.upgrade_state['votes'], 1)
        self.assertEqual(self.upgrade.upgrade_state['voters'], 6)

        self.assertEqual(self.upgrade.upgrade_state['pepper'], '123xyz')
        self.assertEqual(self.upgrade.upgrade_state['cilantro_branch_name'], 'hello1')
        self.assertEqual(self.upgrade.upgrade_state['contracting_branch_name'], 'hello2')

        self.assertEqual(self.upgrade.has_voted[self.mn_wallets[0]], True)

    def test_second_vote_fails_if_already_voted(self):
        self.upgrade.vote(
            signer=self.mn_wallets[0],
            cilantro_branch_name='hello1',
            contracting_branch_name='hello2',
            pepper='123xyz'
        )

        with self.assertRaises(AssertionError):
            self.upgrade.vote(signer=self.mn_wallets[0])

    def test_non_voter_cannot_vote(self):
        with self.assertRaises(AssertionError):
            self.upgrade.vote(signer='someone')

    def test_two_thirds_sets_consensus_to_true(self):
        self.upgrade.vote(
            signer=self.mn_wallets[0],
            cilantro_branch_name='hello1',
            contracting_branch_name='hello2',
            pepper='123xyz'
        )

        self.upgrade.vote(signer=self.mn_wallets[1])
        self.upgrade.vote(signer=self.mn_wallets[2])
        self.upgrade.vote(signer=self.dn_wallets[0])

        self.assertTrue(self.upgrade.upgrade_state['consensus'])

    def test_build_pepper(self):
        p = build_pepper()
        self.assertEqual(p, p)

    def test_git_branch(self):
        path = os.path.join(os.path.dirname(cilantro_ee.__file__), '..')
        os.chdir(path)

        from subprocess import check_output
        new_branch_name = check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).rstrip().decode()
        print(new_branch_name)
        old_branch = get_version()
        flag = 'ori1-rel-gov-socks-upg' == old_branch
        self.assertFalse(flag)
