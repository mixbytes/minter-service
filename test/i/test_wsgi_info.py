import unittest
import web3
import wsgi_ico_info
import tempfile
import yaml
import json
import os


class TestWsgiInfo(unittest.TestCase):

    def setUp(self):
        self.fd, self.path = tempfile.mkstemp()
        contract = {}
        with open('../../build/contracts/MockMinterCompatibleICO.json', 'r') as contract_file:
            contract = json.load(contract_file)

        address = list(contract['networks'].values())[-1]['address']

        with open(self.path, 'w') as f:
            yaml.dump({
                'web3_provider': {
                    'args': ['http://localhost:8545'],
                    'class': 'HTTPProvider'
                },

                'info_contract_address': address}, stream=f, default_flow_style=False)

        wsgi_ico_info.app.config['TESTING'] = True
        self.app = wsgi_ico_info.app.test_client()
        with wsgi_ico_info.app.app_context():
            wsgi_ico_info.init(self.path, '../../build/contracts')

    def tearDown(self):
        os.close(self.fd)

    def test_is_sale_active(self):
        self.assertTrue(json.loads(self.app.get(
            '/isSaleActive').data)['is_sale_active'])

    def test_estimate(self):
        self.assertEqual(self.app.get(
            '/estimateTokens').status_code, 400, msg='without ether')
        self.assertEqual(json.loads(self.app.get(
            '/estimateTokens?ether=1').data)['tokens'], '1000000000000000000')

    def test_token_balance(self):
        self.assertEqual(self.app.get(
            '/getTokenBalance').status_code, 400, msg='without address')
        self.assertEqual(self.app.get(
            '/getTokenBalance?address=dadas').status_code, 400, msg='invalid address')

        self.assertEqual(json.loads(self.app.get(
            '/getTokenBalance?address=0x123f681646d4a755815f9cb19e1acc8565a0c2ac').data)['balance'], '0')
