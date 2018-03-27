#!/usr/bin/env python3

import sys
import os

from web3 import Web3
from flask import Flask, abort, request, jsonify
import logging
from uwsgidecorators import timer
from mixbytes.minter import MinterService

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

conf_filename = os.path.join(os.path.dirname(__file__), '..', 'conf', 'minter.conf')
contracts_directory = os.path.join(os.path.dirname(__file__), '..', 'built_contracts')

app = Flask(__name__)
wsgi_minter = MinterService(conf_filename, contracts_directory, wsgi_mode=True)


@timer(300)
def unlock_account(signum):
    wsgi_minter.unlockAccount()


@app.route('/mintTokens')
def mint_tokens():
    wsgi_minter.mint_tokens(_get_mint_id(), _get_address(), _get_tokens())
    return jsonify({'success': True})


@app.route('/getMintingStatus')
def get_minting_status():
    return jsonify({ 'status': wsgi_minter.get_minting_status(_get_mint_id())})


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
