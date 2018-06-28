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

contracts_registry.add_contract(
    'token', conf['token_contract_address'], 'ERC20')


@app.route('/estimateTokens')
def estimateTokens():
    try:
        tokens = str(contracts_registry.ico_info.estimate(
            Web3.toWei(_get_ethers(), 'ether')))
    except:
        payment = Web3.toWei(_get_ethers(), 'ether')

        m_currentTokensSold = contracts_registry.ico_info._contract.call().m_currentTokensSold()
        centsPerToken = contracts_registry.ico_info._contract.call().c_centsPerToken()
        m_ETHPriceInCents = contracts_registry.ico_info._contract.call().m_ETHPriceInCents()
        c_maximumTokensSold = contracts_registry.ico_info._contract.call().c_maximumTokensSold()

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
        tokens = str(Decimal(contracts_registry.ico_info.purchasedTokenBalanceOf(
            _get_address())))
    except:
        tokens = str(Decimal(contracts_registry.token.balanceOf(
            _get_address())))

    return jsonify({
        'balance': tokens
    })


@app.route('/getEtherFunds')
def ethBalance():
    try:
        ethers = str(Decimal(contracts_registry.ico_info.sentEtherBalanceOf(
            _get_address())))
    except:
        ethers = str(0)
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
