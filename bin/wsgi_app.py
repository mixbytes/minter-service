#!/usr/bin/env python36

import os
import logging
import logging.config

from web3 import Web3

from flask import Flask, abort, request, jsonify

from uwsgidecorators import timer
from mixbytes.minter import MinterService
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
    __file__), '..', 'conf', 'minter.conf')
contracts_directory = os.path.join(
    os.path.dirname(__file__), '..', 'built_contracts')

app = Flask(__name__)
conf = ConfigurationBase(conf_filename)
wsgi_minter = MinterService(conf, contracts_directory, wsgi_mode=True)

contracts_registry = ContractsRegistry(
    conf.get_provider(), contracts_directory)

assert 'info_contract_address' in conf

contracts_registry.add_contract(
    'ico_info', conf['info_contract_address'], 'IICOInfo')


@timer(300)
def unlock_account(signum):
    wsgi_minter.unlockAccount()


@timer(60)
def resend_pending_transactions(signum):
    wsgi_minter.resend_pending_transactions()


@app.route('/mintTokens')
def mint_tokens():
    if not contracts_registry.ico_info.isSaleActive():
        return jsonify({
            'success': False,
            'message': 'sale is not active'
        })

    wsgi_minter.mint_tokens(_get_mint_id(), _get_address(), _get_tokens())
    return jsonify({'success': True})


@app.route('/getMintingStatus')
def get_minting_status():
    return jsonify(wsgi_minter.get_minting_status(_get_mint_id()))


@app.route('/blockChainHeight')
def get_blockchain_height():
    return jsonify(wsgi_minter.blockchain_height())


def _get_mint_id():
    """
    Extracts mint id from current request parameters.
    :return: mint id
    """
    mint_id = request.args['mint_id']
    assert isinstance(mint_id, (str, bytes))

    if 0 == len(mint_id):
        abort(400, 'empty mint_id')

    return mint_id


def _get_address():
    return _validate_address(request.args['address'])


def _get_tokens():
    tokens = request.args['tokens_amount']
    try:
        return int(tokens)
    except ValueError:
        abort(400, 'bad tokens_amount')


def _validate_address(address):
    if not Web3.isAddress(address):
        abort(400, 'bad address')
    return address


if __name__ == '__main__':
    app.run()
