#!/usr/bin/env python3

import os
import logging
import logging.config

from web3 import Web3

from flask import Flask, abort, request, jsonify

from decimal import Decimal
from mixbytes.conf import ConfigurationBase
from mixbytes.contract import ContractsRegistry
import sys

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

_conf_filename = os.environ.get('CONFIG_FILE', None) or os.path.join(os.path.dirname(
    __file__), '..', 'conf', 'ico_info.conf')

_contracts_directory = os.path.join(
    os.path.dirname(__file__), '..', 'built_contracts')

app = Flask(__name__)


this = sys.modules[__name__]

contracts_registry = None


def init(conf_filename=None, contracts_directory=None):
    conf = ConfigurationBase(conf_filename)

    this.contracts_registry = ContractsRegistry(
        conf.get_provider(), contracts_directory)

    assert 'info_contract_address' in conf

    this.contracts_registry.add_contract(
        'ico_info', conf['info_contract_address'], 'IICOInfo')
    this.contracts_registry.add_contract(
        'token', conf['token_contract_address'], 'ERC20')


if __name__ != "__main__":
    try:
        init(_conf_filename, _contracts_directory)
    except Exception:
        logger.warn(
            "Can't instantiate with default config and contract directory")


def main():
    app.run()


@app.route('/estimateTokens')
def estimateTokens():
    try:
        tokens = str(this.contracts_registry.ico_info.estimate(
            Web3.toWei(_get_ethers(), 'ether')))
    except:
        payment = Web3.toWei(_get_ethers(), 'ether')

        m_currentTokensSold = this.contracts_registry.ico_info._contract.call().m_currentTokensSold()
        centsPerToken = this.contracts_registry.ico_info._contract.call().c_centsPerToken()
        m_ETHPriceInCents = this.contracts_registry.ico_info._contract.call().m_ETHPriceInCents()
        c_maximumTokensSold = this.contracts_registry.ico_info._contract.call().c_maximumTokensSold()

        # amount that can be bought depending on the price
        tokenAmount = (payment * m_ETHPriceInCents) / centsPerToken

        # number of tokens available before the cap is reached
        maxTokensAllowed = c_maximumTokensSold - m_currentTokensSold

        # if amount of tokens we can buy is more than the amount available
        if tokenAmount > maxTokensAllowed:
            # price of 1 full token in ether-wei
            # example 60 * 1e18 / 36900 = 0.162 * 1e18 = 0.162 eth
            ethPerToken = (centsPerToken*Web3.toWei(1, 'ether')
                           ) / m_ETHPriceInCents
            # change amount to maximum allowed
            tokenAmount = maxTokensAllowed
            # how much exactly to charge
            payment = (ethPerToken * tokenAmount) / Web3.toWei(1, 'ether')

        # calculating a 20 % bonus if the price of bought tokens is more than $30k
        if (payment * m_ETHPriceInCents) / Web3.toWei(1, 'ether') >= 3000000:
            tokenAmount = tokenAmount + (tokenAmount / 5)

        tokens = str(tokenAmount)

    return jsonify({
        'tokens': tokens
    })


@app.route('/getTokenBalance')
def tokenBalance():
    try:
        tokens = str(Decimal(this.contracts_registry.ico_info.purchasedTokenBalanceOf(
            _get_address())))
    except:
        tokens = str(Decimal(this.contracts_registry.token.balanceOf(
            _get_address())))

    return jsonify({
        'balance': tokens
    })


@app.route('/isSaleActive')
def isSaleActive():

    is_sale_active = this.contracts_registry.ico_info.isSaleActive()
    return jsonify({
        'is_sale_active': is_sale_active
    })

@app.route('/getAcceptedUsd')
def acceptedUsd():
    try:
        acceptedUsd = this.contracts_registry.ico_info._contract.call().m_currentUsdAccepted() / 100
    except Exception as e:
        logger.warn("Unknown method %s" % (str(e)))
        acceptedUsd = 0
    return jsonify({
        'value': acceptedUsd
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
    main()
