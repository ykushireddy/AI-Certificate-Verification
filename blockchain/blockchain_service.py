
import json
import re
from pathlib import Path
from web3 import Web3

BASE_DIR = Path(__file__).resolve().parent.parent

RPC_URL = "http://127.0.0.1:8545"

ABI_PATH = BASE_DIR / "blockchain" / "contract_abi.json"
DEPLOYMENT_PATH = BASE_DIR / "deployments" / "localhost.json"

# Connect to local Ethereum blockchain
w3 = Web3(Web3.HTTPProvider(RPC_URL))


def load_contract():
    if not w3.is_connected():
        raise ConnectionError(
            "Cannot connect to Ethereum. Start the Hardhat node first."
        )

    with open(ABI_PATH, "r", encoding="utf-8") as file:
        contract_abi = json.load(file)

    with open(DEPLOYMENT_PATH, "r", encoding="utf-8") as file:
        deployment = json.load(file)

    contract_address = Web3.to_checksum_address(
        deployment["contractAddress"]
    )

    contract = w3.eth.contract(
        address=contract_address,
        abi=contract_abi
    )

    return contract


def register_certificate(certificate_id, certificate_hash):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", certificate_hash):
        raise ValueError("Invalid SHA-256 certificate hash.")

    contract = load_contract()

    # First account provided by Hardhat local blockchain
    account = w3.eth.accounts[0]

    transaction_hash = contract.functions.registerCertificate(
        certificate_id,
        certificate_hash
    ).transact({
        "from": account
    })

    receipt = w3.eth.wait_for_transaction_receipt(
        transaction_hash
    )

    if receipt["status"] != 1:
        raise RuntimeError("Certificate registration failed.")

    return {
        "certificate_id": certificate_id,
        "transaction_hash": transaction_hash.hex(),
        "block_number": receipt["blockNumber"],
        "status": "REGISTERED"
    }


def verify_certificate(certificate_id):
    contract = load_contract()

    result = contract.functions.verifyCertificate(
        certificate_id
    ).call()

    certificate_hash, issuer, timestamp, exists = result

    if not exists:
        return {
            "exists": False,
            "status": "NOT FOUND"
        }

    return {
        "exists": True,
        "certificate_id": certificate_id,
        "certificate_hash": certificate_hash,
        "issuer": issuer,
        "timestamp": timestamp,
        "status": "REGISTERED"
    }
