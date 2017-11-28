
import os
import sys
import subprocess
import unittest
from shutil import rmtree
from os.path import join
import logging
import json

import yaml

sys.path.append(os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..', 'lib')))

from mixbytes.minter import MinterService, UsageError


class TestMinterService(unittest.TestCase):
    """
    Test requires testrpc (with option -u 0) and redis to be running. See basic.conf.
    """

    @classmethod
    def setUpClass(cls):
        root_dir = os.path.realpath(join(os.path.dirname(__file__), '..', '..'))
        bin_dir = join(root_dir, 'bin')
        test_dir = os.path.realpath(os.path.dirname(__file__))
        universe_dir = join(test_dir, 'UNIVERSE')
        install_dir = join(universe_dir, 'install')
        data_dir = join(universe_dir, 'data')

        cls._root_dir = root_dir

        if os.path.exists(universe_dir):
            rmtree(universe_dir)
        os.makedirs(universe_dir)

        logging.basicConfig(filename=join(universe_dir, 'test.log'), level=logging.DEBUG)

        subprocess.check_call([join(bin_dir, 'deploy'), install_dir])

        os.makedirs(data_dir)

        with open(join(test_dir, 'basic.conf')) as fh:
            conf = yaml.safe_load(fh)

        conf['data_directory'] = data_dir

        cls._install_dir = install_dir
        cls._conf_file = join(install_dir, 'conf', 'minter.conf')
        with open(cls._conf_file, 'w') as fh:
            yaml.safe_dump(conf, fh, default_flow_style=False)

    @classmethod
    def createMinter(cls, wsgi_mode=False):
        return MinterService(cls._conf_file, join(cls._install_dir, 'built_contracts'), wsgi_mode)


    def test_1_init_account(self):
        minter = self.__class__.createMinter()
        address = minter.init_account()
        self.__class__.minter_account = address

        with self.assertRaises(UsageError):
            # second time is no-no
            self.__class__.createMinter().init_account()

        # sending ether to the account
        w3 = minter.create_web3()
        w3.eth.sendTransaction({'from': w3.eth.accounts[0], 'to': address, 'value': w3.toWei(1, 'ether')})


    def test_2_deploy_contract(self):
        minter = self.__class__.createMinter()
        w3 = minter.create_web3()

        contract_json = self._token_json()
        token_contract = w3.eth.contract(abi=contract_json['abi'], bytecode=contract_json['unlinked_binary'])
        tx_hash = token_contract.deploy(transaction={'from': w3.eth.accounts[0]})

        self.__class__._token_address = w3.eth.getTransactionReceipt(tx_hash)['contractAddress']

        address = minter.deploy_contract(self._token_address)

        token_contract.transact({'from': w3.eth.accounts[0], 'to': self._token_address}).transferOwnership(address)


    def test_3_minting(self):
        minter = self.__class__.createMinter(True)
        w3 = minter.create_web3()

        token_contract = w3.eth.contract(address=self.__class__._token_address, abi=self._token_json()['abi'])

        investor1 = w3.eth.accounts[1]
        investor2 = w3.eth.accounts[2]
        investor3 = w3.eth.accounts[3]

        self.assertEqual(token_contract.call().balanceOf(investor1), 0)
        self.assertEqual(token_contract.call().balanceOf(investor2), 0)

        minter.mint_tokens('m1', investor1, 10000)
        self.assertEqual(minter.get_minting_status('m1'), 'minted')
        self.assertEqual(minter.get_minting_status('zz'), 'not_minted')
        self.assertEqual(token_contract.call().balanceOf(investor1), 10000)
        self.assertEqual(token_contract.call().balanceOf(investor2), 0)

        minter.mint_tokens('m2', investor2, 12000)
        self.assertEqual(minter.get_minting_status('m1'), 'minted')
        self.assertEqual(minter.get_minting_status('m2'), 'minted')
        self.assertEqual(token_contract.call().balanceOf(investor1), 10000)
        self.assertEqual(token_contract.call().balanceOf(investor2), 12000)

        minter.mint_tokens('m1', investor1, 10000)
        self.assertEqual(minter.get_minting_status('m1'), 'minted')
        self.assertEqual(token_contract.call().balanceOf(investor1), 10000)
        self.assertEqual(token_contract.call().balanceOf(investor2), 12000)

        minter.mint_tokens('m1', investor2, 12000)
        self.assertEqual(minter.get_minting_status('m1'), 'minted')
        self.assertEqual(token_contract.call().balanceOf(investor1), 10000)
        self.assertEqual(token_contract.call().balanceOf(investor2), 12000)

        minter.mint_tokens('m3', investor1, 8000)
        self.assertEqual(minter.get_minting_status('m1'), 'minted')
        self.assertEqual(minter.get_minting_status('m2'), 'minted')
        self.assertEqual(minter.get_minting_status('m3'), 'minted')
        self.assertEqual(minter.get_minting_status('yy'), 'not_minted')
        self.assertEqual(token_contract.call().balanceOf(investor1), 18000)
        self.assertEqual(token_contract.call().balanceOf(investor2), 12000)
        self.assertEqual(token_contract.call().balanceOf(investor3), 0)

        minter.close()


    def test_4_recover_ether(self):
        minter = self.__class__.createMinter()
        w3 = minter.create_web3()

        tx_hash = minter.recover_ether(w3.eth.accounts[0])
        self.assertEqual(w3.eth.getTransactionReceipt(tx_hash).status, 1)

        self.assertTrue(w3.eth.getBalance(self.__class__.minter_account) < w3.toWei(0.2, 'ether'))


    def _token_json(self):
        with open(join(self.__class__._root_dir, 'build', 'contracts', 'SimpleMintableToken.json')) as fh:
            return json.load(fh)
