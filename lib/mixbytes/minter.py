
import os
import json
import logging
import copy
import stat
from time import sleep

import yaml
from web3 import Web3, HTTPProvider, IPCProvider


import redis
import redis.exceptions

from mixbytes.filelock import FileLock, WouldBlockError
from mixbytes.conf import ConfigurationBase
from mixbytes import contract
import functools
import math
from toolz import assoc, merge

logger = logging.getLogger(__name__)


VALID_TRANSACTION_PARAMS = [
    'from',
    'to',
    'gas',
    'gasPrice',
    'value',
    'data',
    'nonce',
    'chainId',
]


class MinterService(object):
    TX_BLOCK_HEIGHT_KEY_PREFIX = 'bh'
    PENDING_TRANSACTIONS_SET_KEY = 'pending_transactions'
    TX_MINT_ID_KEY_PREFIX = 'mid_'

    def __init__(self, config, contracts_directory, wsgi_mode=False):

        self._conf = _Conf(config.filename)
        self.contracts_directory = contracts_directory
        self.wsgi_mode = wsgi_mode

        self._wsgi_mode_state = self._load_state() if wsgi_mode else None
        self._w3 = self.create_web3()
        self._redis = self._conf.get_redis() if wsgi_mode else None

        self.__target_contract = None

        if wsgi_mode:
            self.unlockAccount()
        self.pending_transactions = False
        self.filter_id = None

    def unlockAccount(self):
        logger.debug("Unlock account %s" %
                     (self._wsgi_mode_state.get_account_address()))
        if 'password' in self._wsgi_mode_state['account']:
            self._w3.personal.unlockAccount(self._wsgi_mode_state.get_account_address(),
                                            self._wsgi_mode_state['account']['password'],
                                            600)

    def blockchain_height(self):
        return self._w3.eth.blockNumber

    def mint_tokens(self, mint_id, address, tokens):
        """
        Mints tokens
        :param mint_id: str | bytes, unique mint id for the request
        :param address: valid web3 address
        :param tokens: int, tokens to mint (in wei)
        :return: hash of the transaction
        """
        assert self.wsgi_mode

        mint_id = self.__class__._prepare_mint_id(mint_id)

        gas_price = self._w3.eth.gasPrice
        gas_limit = self._gas_limit()

        tx_hash = self._target_contract() \
            .transact({'from': self._wsgi_mode_state.get_account_address(), 'gasPrice': gas_price, 'gas': gas_limit}) \
            .mint(mint_id, address, tokens)

        # remembering tx hash for get_minting_status references - optional step
        _silent_redis_call(self._redis.lpush, self._redis_mint_tx_key(
            mint_id), Web3.toBytes(hexstr=tx_hash))

        _silent_redis_call(self._redis.set, self._redis_tx_mint_id_key(
            tx_hash), mint_id, ex=3600)

        logger.info("add pending transaction %s" % (tx_hash))
        _silent_redis_call(
            self._redis.sadd, self.PENDING_TRANSACTIONS_SET_KEY, Web3.toBytes(hexstr=tx_hash))

        logger.debug('mint_tokens(): mint_id=%s, address=%s, tokens=%d, gas_price=%d, gas=%d: sent tx %s',
                     Web3.toHex(mint_id), address, tokens, gas_price, gas_limit, tx_hash)

        return tx_hash

    def _build_status(self, status, **kwargs):
        res = {'status': status}
        for k, v in kwargs.items():
            res[k] = v
        return res

    def _redis_tx_mint_id_key(self, tx_hash):
        return self.TX_MINT_ID_KEY_PREFIX + tx_hash

    def get_minting_status(self, mint_id) -> dict:
        """
        Query current status of mint request
        :param mint_id: str | bytes, unique mint id for the request
        :return: str, status code
        """
        assert self.wsgi_mode

        mint_id = self.__class__._prepare_mint_id(mint_id)

        w3_instance = self._w3
        conf = self._conf

        if self._get_minting_status_is_confirmed(mint_id):
            return self._build_status('minted')

        # Checking if it was mined recently (still subject to removal from blockchain!).
        if conf.get('require_confirmations', 0) > 0 and self._target_contract().call().m_processed_mint_id(mint_id):
            current_block_number = self._w3.eth.blockNumber
            mint_id_block = _silent_redis_call(self._redis.get, self._redis_mint_tx_key(
                mint_id, self.TX_BLOCK_HEIGHT_KEY_PREFIX))
            if not mint_id_block:
                _silent_redis_call(self._redis.set, self._redis_mint_tx_key(
                    mint_id, self.TX_BLOCK_HEIGHT_KEY_PREFIX), self._w3.eth.blockNumber, ex=3600)

            start_mint_block = int(mint_id_block or current_block_number)
            confirmations = current_block_number - start_mint_block
            rest_confirmations = conf.get(
                'require_confirmations', 0) - confirmations
            return self._build_status('minting', confirmations=confirmations, rest_confirmations=rest_confirmations)

        # finding all known transaction ids which could mint this mint_id
        tx_bin_ids = _silent_redis_call(
            self._redis.lrange, self._redis_mint_tx_key(mint_id), 0, -1) or []

        # getting transactions
        txs = list(filter(None, (w3_instance.eth.getTransaction(
            Web3.toHex(tx_id)) for tx_id in tx_bin_ids)))

        # searching for failed transactions
        for tx in txs:

            if tx.blockNumber is None:
                continue  # not mined yet

            receipt = w3_instance.eth.getTransactionReceipt(tx.hash)
            if receipt is None:
                continue  # blockchain reorg?

            if 0 == get_receipt_status(receipt):
                # If any of the transactions has failed, it's a very bad sign
                # (failure due to reentrance should't be possible, see ReenterableMinter).
                return self._build_status('failed')

        if txs:
            # There is still hope.
            return self._build_status('minting', confirmations=0, rest_confirmations=conf.get('require_confirmations', 0))
        else:
            # Last chance - maybe we're out of sync?
            if w3_instance.eth.syncing:
                return self._build_status('node_syncing')

            # There are no signs of minting - now its vise for client to re-mint this mint_id.
            return self._build_status('not_minted')

    def set_account_address(self, address):
        with self._load_state() as state:
            state['account'] = {
                'address': address
            }
            state.save(True)

    def init_account(self):
        """
        Initializes ethereum external account to use for minting
        :return: account address
        """
        with self._load_state() as state:
            if state.account_address is not None:
                raise UsageError(
                    'Account is already initialized (address: {})', state.account_address)

            password = Web3.sha3(os.urandom(100))[2:42]
            address = self._w3.personal.newAccount(password)
            assert Web3.isAddress(address)

            state['account'] = {
                'password': password,
                'address': address,
            }
            state.save(True)

            return address

    def get_or_init_account(self, address=None):
        state = self._load_state()

        if state.account_address is not None:

            res = state.account_address
        else:
            state.close()
            res = self.init_account()

        state.close()
        return res

    def is_contract_deployed(self):
        try:
            self._wsgi_mode_state.get_minter_contract_address()
            return True
        except RuntimeError:
            return False

    def prepare_replacement_transaction(self, web3, current_transaction, new_transaction):
        # if current_transaction['blockNumber'] is not None:
        #     raise ValueError('Supplied transaction with hash {} has already been mined'
        #                      .format(current_transaction['hash']))
        if 'nonce' in new_transaction and new_transaction['nonce'] != current_transaction['nonce']:
            raise ValueError(
                'Supplied nonce in new_transaction must match the pending transaction')

        if 'nonce' not in new_transaction:
            new_transaction = assoc(
                new_transaction, 'nonce', current_transaction['nonce'])

        if 'gasPrice' in new_transaction:
            if new_transaction['gasPrice'] <= current_transaction['gasPrice']:
                raise ValueError(
                    'Supplied gas price must exceed existing transaction gas price')
        else:
            generated_gas_price = web3.eth.generateGasPrice(new_transaction)
            minimum_gas_price = int(
                math.ceil(current_transaction['gasPrice'] * 1.1))
            if generated_gas_price and generated_gas_price > minimum_gas_price:
                new_transaction = assoc(
                    new_transaction, 'gasPrice', generated_gas_price)
            else:
                new_transaction = assoc(
                    new_transaction, 'gasPrice', minimum_gas_price)

        return new_transaction

    def replace_transaction(self, web3, current_transaction, new_transaction):
        new_transaction = self.prepare_replacement_transaction(
            web3, current_transaction, new_transaction
        )
        return web3.eth.sendTransaction(new_transaction)

    def get_required_transaction(self, web3, transaction_hash):
        current_transaction = web3.eth.getTransaction(transaction_hash)
        if not current_transaction:
            raise ValueError('Supplied transaction with hash {} does not exist'
                             .format(transaction_hash))
        return current_transaction

    def replaceTransaction(self, web3, transaction_hash, new_transaction):
        current_transaction = self.get_required_transaction(
            web3, transaction_hash)

        return self.replace_transaction(web3, current_transaction, new_transaction)

    def extract_valid_transaction_params(self, transaction_params):
        extracted_params = {key: transaction_params[key]
                            for key in VALID_TRANSACTION_PARAMS if key in transaction_params}

        if extracted_params.get('data') is not None:
            if transaction_params.get('input') is not None:
                if extracted_params['data'] != transaction_params['input']:
                    msg = 'failure to handle this transaction due to both "input: {}" and'
                    msg += ' "data: {}" are populated. You need to resolve this conflict.'
                    err_vals = (
                        transaction_params['input'], extracted_params['data'])
                    raise AttributeError(msg.format(*err_vals))
                else:
                    return extracted_params
            else:
                return extracted_params
        elif extracted_params.get('data') is None:
            if transaction_params.get('input') is not None:
                return assoc(extracted_params, 'data', transaction_params['input'])
            else:
                return extracted_params
        else:
            raise Exception(
                "Unreachable path: transaction's 'data' is either set or not set")

    def modifyTransaction(self, web3, transaction_hash, **transaction_params):
        #  assert_valid_transaction_params(transaction_params)
        current_transaction = self.get_required_transaction(
            web3, transaction_hash)
        current_transaction_params = self.extract_valid_transaction_params(
            current_transaction)
        new_transaction = merge(current_transaction_params, transaction_params)

        return self.replace_transaction(web3, current_transaction, new_transaction)

    def resend_pending_transactions(self):
        w3_instance = self._w3
        if not self.pending_transactions:
            self.pending_transactions = True
            pending_txs_for_addr = w3_instance.txpool.content['pending'].get(
                self._wsgi_mode_state.get_account_address(), {})
            for txs in pending_txs_for_addr.values():
                if type(txs) is list:
                    hashes = map(lambda e: e['hash'], txs)
                else:
                    hashes = [txs['hash']]
                for hash_ in hashes:
                    logger.info(
                        "init pending transaction from node %s" % (hash_))
                    _silent_redis_call(
                        self._redis.sadd, self.PENDING_TRANSACTIONS_SET_KEY, Web3.toBytes(hexstr=hash_))

        # finding all known pending transactions
        tx_bin_ids = _silent_redis_call(
            self._redis.smembers, self.PENDING_TRANSACTIONS_SET_KEY) or []

        # getting transactions
        txs = []

        for tx_id in tx_bin_ids:

            tx = w3_instance.eth.getTransaction(Web3.toHex(tx_id))

            if tx is None:
                logger.info("remove not existed transaction %s" % (
                    Web3.toHex(tx_id)))
                _silent_redis_call(
                    self._redis.srem, self.PENDING_TRANSACTIONS_SET_KEY, tx_id)
            else:
                txs.append(tx)

        for tx in txs:

            if tx.blockNumber is None:

                new_gas_price = int(tx.gasPrice * 1.1)

                new_tx_hash = self.modifyTransaction(w3_instance, tx.hash,
                                                     gasPrice=new_gas_price)
                logger.info("replace transaction %s with %s and new gas price %d" % (
                    tx.hash, new_tx_hash, new_gas_price))
                _silent_redis_call(
                    self._redis.srem, self.PENDING_TRANSACTIONS_SET_KEY, Web3.toBytes(hexstr=tx.hash))
                _silent_redis_call(
                    self._redis.sadd, self.PENDING_TRANSACTIONS_SET_KEY, Web3.toBytes(hexstr=new_tx_hash))
                mint_id = _silent_redis_call(
                    self._redis.get, self._redis_tx_mint_id_key(tx.hash))

                if mint_id is not None:
                    _silent_redis_call(self._redis.delete,
                                       self._redis_tx_mint_id_key(tx.hash))
                    _silent_redis_call(
                        self._redis.set, self._redis_tx_mint_id_key(new_tx_hash), mint_id, ex=3600)

                    _silent_redis_call(self._redis.lpush, self._redis_mint_tx_key(
                        Web3.toBytes(mint_id)), Web3.toBytes(hexstr=new_tx_hash))

            else:
                logger.info("remove non pending transaction %s" % (
                    tx.hash))
                _silent_redis_call(
                    self._redis.srem, self.PENDING_TRANSACTIONS_SET_KEY, Web3.toBytes(hexstr=tx.hash))

    def deploy_contract(self, token_address):
        """
        Deploys new ReenterableMinter contract
        :param token_address: address of the minted token
        :return: ReenterableMinter address
        """
        w3_instance = self._w3

        gas_price = w3_instance.eth.gasPrice
        gas_limit = int(w3_instance.eth.getBlock('latest').gasLimit * 0.9)

        def get_bytecode(json_): return json_.get(
            'bytecode') or json_['unlinked_binary']

        with self._load_state() as state:
            contract = w3_instance.eth.contract(abi=self._built_contract('ReenterableMinter')['abi'],
                                                bytecode=get_bytecode(self._built_contract('ReenterableMinter')))
            print(state['account'])
            if 'password' in state['account']:
                w3_instance.personal.unlockAccount(
                    state.get_account_address(), state['account']['password'])

            tx_hash = contract.deploy(transaction={'from': state.get_account_address(),
                                                   'gasPrice': gas_price, 'gas': gas_limit},
                                      args=[token_address])

            logger.debug('deploy_contract: token_address=%s, gas_price=%d, gas=%d: sent tx %s',
                         token_address, gas_price, gas_limit, tx_hash)

            receipt = self._get_receipt_blocking(tx_hash)
            address = receipt['contractAddress']
            assert Web3.isAddress(address)

            state['minter_contract'] = address
            state['minter_contract_block_num'] = receipt.blockNumber
            state.save(True)

            return address

    def recover_ether(self, target_address):
        """
        To be used after minting will no longer be used: sends remaining ether to specified address
        :param target_address: address to send ether
        :return: hash of transaction or None (in case nothing could be sent)
        """
        with self._load_state() as state:
            self._w3.personal.unlockAccount(
                state.get_account_address(), state['account']['password'])

            gas_price = self._w3.eth.gasPrice
            gas_limit = 50000
            value2send = self._w3.eth.getBalance(
                state.get_account_address()) - gas_limit * gas_price
            if value2send <= 0:
                return None

            tx_hash = self._w3.eth.sendTransaction({'from': state.get_account_address(), 'to': target_address,
                                                    'value': value2send, 'gasPrice': gas_price, 'gas': gas_limit})

            logger.debug('recover_ether: from=%s, target_address=%s, gas_price=%d, gas=%d: sent tx %s',
                         state.get_account_address(), target_address, gas_price, gas_limit, tx_hash)

            self._get_receipt_blocking(tx_hash)
            return tx_hash

    def create_web3(self):
        """
        Utility method
        :return: web3 interface configured with this instance configuration
        """
        return Web3(self._conf.get_provider())

    def get_web3(self):
        return self._w3

    def __exit__(self, type, value, traceback):
        self.close()

    def __enter__(self):
        return self

    def close(self):
        """
        For wsgi mode
        """
        if self.wsgi_mode:
            self._wsgi_mode_state.close()

    def _get_minting_status_is_confirmed(self, prepared_mint_id) -> tuple:
        w3_instance = self._w3
        conf = self._conf

        # as a side effect checking that contract was deployed and we know minter_contract_block_num
        contract = self._target_contract()

        # Checking if it was mined enough block ago.
        if 'require_confirmations' in conf:
            confirmed_block = w3_instance.eth.blockNumber - \
                int(conf['require_confirmations'])
            if confirmed_block < 0:
                # we are at the beginning of blockchain for some reason
                return False
            if self._wsgi_mode_state['minter_contract_block_num'] >= confirmed_block:
                # its too early, calls to m_processed_mint_id will return 0x
                return False

            saved_default = w3_instance.eth.defaultBlock
            w3_instance.eth.defaultBlock = '0x{:x}'.format(confirmed_block)
        else:
            saved_default = None

        try:
            if contract.call().m_processed_mint_id(prepared_mint_id):
                # TODO background eviction thread/process
                _silent_redis_call(self._redis.delete,
                                   self._redis_mint_tx_key(prepared_mint_id))

                return True
        finally:
            if 'require_confirmations' in conf:
                assert saved_default is not None
                w3_instance.eth.defaultBlock = saved_default

        return False

    def _load_state(self):
        return _State(os.path.join(self._conf['data_directory'], 'state.yaml'), lock_shared=self.wsgi_mode)

    def _gas_limit(self):
        # Strange behaviour was observed on Rinkeby with web3py 3.16:
        # looks like web3py set default gas limit a bit above typical block gas limit and ultimately the transaction was
        # completely ignored (getTransactionReceipt AND getTransaction returned None, and the tx was absent in
        # eth.pendingTransactions).
        # That's why 90% of the last block gasLimit should be a safe cap (I'd recommend to limit it further in conf file
        # based on specific token case).

        limit = int(self._w3.eth.getBlock('latest').gasLimit * 0.9)
        return min(int(self._conf['gas_limit']), limit) if 'gas_limit' in self._conf else limit

    def _built_contract(self, contract_name):
        with open(os.path.join(self.contracts_directory, contract_name + '.json')) as fh:
            return json.load(fh)

    def _target_contract(self):
        assert self.wsgi_mode
        if self.__target_contract is None:
            self.__target_contract = self._w3.eth.contract(self._wsgi_mode_state.get_minter_contract_address(),
                                                           abi=self._built_contract('ReenterableMinter')['abi'])

        return self.__target_contract

    def _get_receipt_blocking(self, tx_hash):
        while True:
            receipt = self._w3.eth.getTransactionReceipt(tx_hash)
            if receipt is not None:
                return receipt
            sleep(1)

    def token_address(self):
        try:
            return self._target_contract().call().m_token()
        except RuntimeError:
            return None

    def minter_address(self):
        assert self.wsgi_mode
        return self._wsgi_mode_state.get_minter_contract_address()

    @classmethod
    def _prepare_mint_id(cls, mint_id):
        if not isinstance(mint_id, (str, bytes)):
            raise TypeError('unsupported mint_id type')

        if isinstance(mint_id, str):
            mint_id = mint_id.encode('utf-8')

        return Web3.toBytes(hexstr=Web3.sha3(mint_id))

    def _redis_mint_tx_key(self, mint_id, key_prefix: str = ""):
        """
        Creating unique redis key for current minter contract and mint_id
        :param mint_id: mint id (bytes)
        :return: redis-compatible string
        """
        assert self.wsgi_mode
        contract_address_bytes = Web3.toBytes(
            hexstr=self._wsgi_mode_state.get_minter_contract_address())
        assert 20 == len(contract_address_bytes)

        if key_prefix is None:
            key_prefix = ""

        return key_prefix.encode('utf-8') + Web3.toBytes(hexstr=Web3.sha3(contract_address_bytes + mint_id))


class _Conf(ConfigurationBase):

    def __init__(self, filename):
        super().__init__(filename)
        self._uses_web3 = True

        self._check_dirs('data_directory')

        if 'require_confirmations' in self:
            self._check_ints('require_confirmations')

        if 'gas_limit' in self:
            self._check_ints('gas_limit')

        # TODO validate redis

        if self._uses_web3 and self._conf['web3_provider']['class'] not in ('HTTPProvider', 'IPCProvider'):
            raise TypeError('bad web3 provider')

    def get_redis(self):
        return redis.StrictRedis(
            host=self.get('redis', {}).get('host', '127.0.0.1'),
            port=self.get('redis', {}).get('port', 6379),
            db=self.get('redis', {}).get('db', 0))

    def _check_addresses(self, addresses):
        self._check_strings(addresses)
        for address_name in addresses if isinstance(addresses, (list, tuple)) else (addresses, ):
            if not Web3.isAddress(self._conf[address_name]):
                raise ValueError(address_name + ' is incorrect')


class _State(object):

    def __init__(self, filename, lock_shared=False):
        self._filename = filename

        self._lock = FileLock(filename + ".lock",
                              non_blocking=True, shared=lock_shared)
        try:
            self._lock.lock()   # implicit unlock is at process termination
        except WouldBlockError:
            raise RuntimeError(
                'Can\'t acquire state lock: looks like another instance is running')

        if os.path.isfile(filename):
            with open(filename) as fh:
                self._state = yaml.safe_load(fh)
            self._created = False
        else:
            self._state = dict()
            self._created = True

        self._original = copy.deepcopy(self._state)

    def __enter__(self):
        assert self._lock is not None, "reuse is not possible"
        return self     # already locked

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.unlock()
        self._lock = None

    def __getitem__(self, key):
        assert self._lock is not None
        return self._state[key]

    def __setitem__(self, key, value):
        assert self._lock is not None
        self._state[key] = value

    def __contains__(self, item):
        assert self._lock is not None
        return item in self._state

    def get(self, key, default):
        assert self._lock is not None
        return self._state.get(key, default)

    @property
    def account_address(self):
        return self.get('account', dict()).get('address')

    def get_account_address(self):
        if self.account_address is None:
            raise RuntimeError('account was not initialized')
        return self.account_address

    def get_minter_contract_address(self):
        if 'minter_contract' not in self:
            raise RuntimeError('contract was not deployed')
        return self['minter_contract']

    def save(self, sync=False):
        assert self._lock is not None
        if self._state == self._original:
            return
        with open(self._filename, 'w') as fh:
            if self._created:
                os.chmod(self._filename, stat.S_IRUSR | stat.S_IWUSR)

            yaml.safe_dump(self._state, fh, default_flow_style=False)

            if sync:
                fh.flush()
                os.fsync(fh.fileno())

    def close(self):
        if self._lock:
            self.save()
            self._lock.unlock()
            self._lock = None


def get_receipt_status(receipt):
    return receipt.status if isinstance(receipt.status, int) else int(receipt.status, 16)


def _silent_redis_call(call_fn, *args, **kwargs):
    try:
        return call_fn(*args, **kwargs)
    except redis.exceptions.ConnectionError as exc:
        logger.warning('could not contact redis: %s', exc)
        return None


class UsageError(RuntimeError):
    def __init__(self, message, *args):
        self.message = message.format(*args)
        super().__init__(self.message)
