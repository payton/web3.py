from __future__ import unicode_literals

import os
import signal
import shutil
import socket
import subprocess
import sys
import time
import tempfile

import pytest

from eth_utils import (
    to_wei,
    remove_0x_prefix,
    is_dict,
    is_address,
    force_text,
)

from web3 import Web3

from web3.utils.module_testing import (
    EthModuleTest,
    NetModuleTest,
    VersionModuleTest,
    PersonalModuleTest,
    Web3ModuleTest,
)
from web3.utils.module_testing.math_contract import (
    MATH_BYTECODE,
    MATH_ABI,
)


if sys.version_info.major == 2:
    FileNotFoundError = OSError


@pytest.fixture(scope='session')
def coinbase():
    return '0xdc544d1aa88ff8bbd2f2aec754b1f1e99e1812fd'


@pytest.fixture(scope='session')
def private_key():
    return '0x58d23b55bc9cdce1f18c2500f40ff4ab7245df9a89505e9b1fa4851f623d241d'


KEYFILE_DATA = '{"address":"dc544d1aa88ff8bbd2f2aec754b1f1e99e1812fd","crypto":{"cipher":"aes-128-ctr","ciphertext":"52e06bc9397ea9fa2f0dae8de2b3e8116e92a2ecca9ad5ff0061d1c449704e98","cipherparams":{"iv":"aa5d0a5370ef65395c1a6607af857124"},"kdf":"scrypt","kdfparams":{"dklen":32,"n":262144,"p":1,"r":8,"salt":"9fdf0764eb3645ffc184e166537f6fe70516bf0e34dc7311dea21f100f0c9263"},"mac":"4e0b51f42b865c15c485f4faefdd1f01a38637e5247f8c75ffe6a8c0eba856f6"},"id":"5a6124e0-10f1-4c1c-ae3e-d903eacb740a","version":3}'  # noqa: E501

KEYFILE_PW = 'web3py-test'


DATADIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    'geth-datadir-fixture',
))


@pytest.fixture(scope='session')
def datadir(tmpdir_factory):
    base_dir = tmpdir_factory.mktemp('goethereum')
    datadir = os.path.join(str(base_dir), 'datadir')
    shutil.copytree(DATADIR, datadir)
    return datadir


@pytest.fixture(scope='session')
def keystore(datadir):
    return os.path.join(datadir, 'keystore')


@pytest.fixture(scope='session')
def keyfile(keystore):
    keyfile_path = os.path.join(
        keystore,
        'UTC--2017-08-24T19-42-47.517572178Z--dc544d1aa88ff8bbd2f2aec754b1f1e99e1812fd',
    )
    return keyfile_path


RAW_TXN_ACCOUNT = '0x39eeed73fb1d3855e90cbd42f348b3d7b340aaa6'


@pytest.fixture(scope='session')
def genesis_data(coinbase):
    return {
        "nonce": "0xdeadbeefdeadbeef",
        "timestamp": "0x0",
        "parentHash": "0x0000000000000000000000000000000000000000000000000000000000000000",  # noqa: E501
        "extraData": "0x7765623370792d746573742d636861696e",
        "gasLimit": "0x47d5cc",
        "difficulty": "0x01",
        "mixhash": "0x0000000000000000000000000000000000000000000000000000000000000000",  # noqa: E501
        "coinbase": "0x3333333333333333333333333333333333333333",
        "alloc": {
            remove_0x_prefix(coinbase): {
                'balance': str(to_wei(1000000000, 'ether')),
            },
            remove_0x_prefix(RAW_TXN_ACCOUNT): {
                'balance': str(to_wei(10, 'ether')),
            },
            remove_0x_prefix(UNLOCKABLE_ACCOUNT): {
                'balance': str(to_wei(10, 'ether')),
            },
        },
        "config": {
            "chainId": 131277322940537,  # the string 'web3py' as an integer
            "homesteadBlock": 0,
            "eip155Block": 0,
            "eip158Block": 0
        },
    }


@pytest.fixture(scope='session')
def genesis_file(datadir, genesis_data):
    genesis_file_path = os.path.join(datadir, 'genesis.json')
    return genesis_file_path


@pytest.fixture(scope='session')
def geth_ipc_path(datadir):
    geth_ipc_dir_path = tempfile.mkdtemp()
    _geth_ipc_path = os.path.join(geth_ipc_dir_path, 'geth.ipc')
    yield _geth_ipc_path

    if os.path.exists(_geth_ipc_path):
        os.remove(_geth_ipc_path)


class Timeout(Exception):
    pass


def wait_for_popen(proc, timeout):
    start = time.time()
    try:
        while time.time() < start + timeout:
            if proc.poll() is None:
                time.sleep(0.01)
            else:
                break
    except Timeout:
        pass


def kill_proc_gracefully(proc):
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        wait_for_popen(proc, 13)

    if proc.poll() is None:
        proc.terminate()
        wait_for_popen(proc, 5)

    if proc.poll() is None:
        proc.kill()
        wait_for_popen(proc, 2)


def get_open_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return str(port)


@pytest.fixture(scope='session')
def geth_binary():
    from geth.install import (
        get_executable_path,
        install_geth,
    )

    if 'GETH_BINARY' in os.environ:
        return os.environ['GETH_BINARY']
    elif 'GETH_VERSION' in os.environ:
        geth_version = os.environ['GETH_VERSION']
        _geth_binary = get_executable_path(geth_version)
        if not os.path.exists(_geth_binary):
            install_geth(geth_version)
        assert os.path.exists(_geth_binary)
        return _geth_binary
    else:
        return 'geth'


@pytest.fixture(scope='session')
def geth_port():
    return get_open_port()


@pytest.fixture(scope='session')
def geth_process(geth_binary, datadir, genesis_file, keyfile, geth_ipc_path, geth_port):
    init_datadir_command = (
        geth_binary,
        '--datadir', str(datadir),
        'init',
        str(genesis_file),
    )
    subprocess.check_output(
        init_datadir_command,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    run_geth_command = (
        geth_binary,
        '--datadir', str(datadir),
        '--ipcpath', geth_ipc_path,
        '--nodiscover',
        '--fakepow',
        '--port', geth_port,
    )
    proc = subprocess.Popen(
        run_geth_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    try:
        yield proc
    finally:
        kill_proc_gracefully(proc)
        output, errors = proc.communicate()
        print(
            "Geth Process Exited:\n"
            "stdout:{0}\n\n"
            "stderr:{1}\n\n".format(
                force_text(output),
                force_text(errors),
            )
        )


def wait_for_socket(ipc_path, timeout=30):
    start = time.time()
    while time.time() < start + timeout:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(ipc_path)
            sock.settimeout(timeout)
        except (FileNotFoundError, socket.error):
            time.sleep(0.01)
        else:
            break


@pytest.fixture(scope="session")
def web3(geth_process, geth_ipc_path):
    wait_for_socket(geth_ipc_path)
    _web3 = Web3(Web3.IPCProvider(geth_ipc_path))
    return _web3


@pytest.fixture(scope="session")
def math_contract_factory(web3):
    contract_factory = web3.eth.contract(abi=MATH_ABI, bytecode=MATH_BYTECODE)
    return contract_factory


@pytest.fixture(scope="session")
def math_contract_deploy_txn_hash(web3, math_contract_factory):
    return '0xceff41630d37e3ef7561e1200eae9dc65da7bbb554ebe46cdc9a20ad77947b1d'


@pytest.fixture(scope="session")
def math_contract(web3, math_contract_factory, math_contract_deploy_txn_hash):
    deploy_receipt = web3.eth.getTransactionReceipt(math_contract_deploy_txn_hash)
    assert is_dict(deploy_receipt)
    contract_address = deploy_receipt['contractAddress']
    assert is_address(contract_address)
    return math_contract_factory(contract_address)


@pytest.fixture
def unlocked_account(web3):
    coinbase = web3.eth.coinbase
    web3.personal.unlockAccount(coinbase, KEYFILE_PW)
    yield coinbase
    web3.personal.lockAccount(coinbase)


UNLOCKABLE_PRIVATE_KEY = '0x392f63a79b1ff8774845f3fa69de4a13800a59e7083f5187f1558f0797ad0f01'
UNLOCKABLE_ACCOUNT = '0x12efdc31b1a8fa1a1e756dfd8a1601055c971e13'


@pytest.fixture(scope='session')
def unlockable_account_pw(web3):
    return KEYFILE_PW


@pytest.fixture(scope="session")
def unlockable_account(web3, unlockable_account_pw):
    yield UNLOCKABLE_ACCOUNT
    web3.personal.lockAccount(UNLOCKABLE_ACCOUNT)


@pytest.fixture(scope="session")
def funded_account_for_raw_txn(web3):
    return RAW_TXN_ACCOUNT


@pytest.fixture(scope="session")
def empty_block_hash():
    return "0xf847e8f4bf2047490797ac2cd0c86d5fede279f7704a62c3bae548898638af1e"


@pytest.fixture(scope="session")
def empty_block(web3, empty_block_hash):
    block = web3.eth.getBlock(empty_block_hash)
    return block


@pytest.fixture(scope="session")
def block_with_txn_hash():
    return '0x9d6b58c1e9790b79a4130db250dcc5c39afc5c8748c5d03d3c2b649bd47ceb48'


@pytest.fixture(scope="session")
def block_with_txn(web3, block_with_txn_hash):
    block = web3.eth.getBlock(block_with_txn_hash)
    return block


@pytest.fixture(scope="session")
def mined_txn_hash(block_with_txn):
    return block_with_txn['transactions'][0]


class TestGoEthereum(Web3ModuleTest):
    def _check_web3_clientVersion(self, client_version):
        assert client_version.startswith('Geth/')


class TestGoEthereumEthModule(EthModuleTest):
    pass


class TestGoEthereumVersionModule(VersionModuleTest):
    pass


class TestGoEthereumNetModule(NetModuleTest):
    pass


class TestGoEthereumPersonalModule(PersonalModuleTest):
    pass
