#!/usr/bin/env python3

import os
import logging
import logging.config

from web3 import Web3

from flask import Flask, abort, request, jsonify

from decimal import Decimal
from mixbytes.conf import ConfigurationBase
from mixbytes.contract import ContractsRegistry

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        }
    },
    'handlers': {
        'default': {
            'level': os.environ.get("LOG_LEVEL", logging.getLevelName(logging.DEBUG)),
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout'
        }
    },
    'root': {
        'handlers': ['default'],
        'level': os.environ.get("LOG_LEVEL", logging.getLevelName(logging.DEBUG))
    }
})

logger = logging.getLogger(__name__)

conf_filename = os.path.join(os.path.dirname(
    __file__), '..', 'conf', 'ico_info.conf')
contracts_directory = os.path.join(
    os.path.dirname(__file__), '..', 'built_contracts')

app = Flask(__name__)
conf = ConfigurationBase(conf_filename)
contracts_registry = ContractsRegistry(
    conf.get_provider(), contracts_directory)

assert 'info_contract_address' in conf

contracts_registry.add_contract(
    'ico_info', conf['info_contract_address'], 'IICOInfo')


@app.route('/estimateTokens')
def estimateTokens():
    tokens = str(contracts_registry.ico_info.estimate(
        Web3.toWei(_get_ethers(), 'ether')))
    return jsonify({
        'tokens': tokens
    })


@app.route('/getTokenBalance')
def tokenBalance():
    tokens = str(Decimal(contracts_registry.ico_info.purchasedTokenBalanceOf(
        _get_address())))
    return jsonify({
        'balance': tokens
    })


@app.route('/getEtherFunds')
def ethBalance():
    ethers = str(Decimal(contracts_registry.ico_info.sentEtherBalanceOf(
        _get_address())))
    return jsonify({
        'funds': ethers
    })


def _get_ethers():
    ether = request.args['ether']
    try:
        return int(ether)
    except ValueError:
        pass
    try:
        return float(ether)
    except ValueError:
        abort(400, 'bad ether')


def _get_address():
    return _validate_address(request.args['address'])


def _validate_address(address):
    if not Web3.isAddress(address):
        abort(400, 'bad address')
    return address


if __name__ == '__main__':
    app.run()
