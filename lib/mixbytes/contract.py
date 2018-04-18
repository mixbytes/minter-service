from decimal import Decimal
import re
import os
import json
import types


class Contract():
    def __init__(self, web3, address, contract_path):

        self._validate_address(address)
        self._contract = web3.eth.contract(
            address, abi=self._built_contract(contract_path)['abi'])

    def __getattr__(self, function_name):
        return self._contract.call().__getattr__(function_name)

    def _built_contract(self, contract_name):

        with open(os.path.join(contract_name)) as fh:
            return json.load(fh)

    def _validate_address(self, address):
        if not re.match(r'^(?:0x)?[a-f0-9]{1,40}$', address, re.I):
            raise ArgumentError(address)
