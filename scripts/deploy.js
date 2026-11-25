
import { network } from "hardhat";
import fs from "node:fs";
import path from "node:path";

async function main() {
    console.log("Connecting to local Ethereum blockchain...");

    const { ethers } = await network.connect();

    const [deployer] = await ethers.getSigners();

    console.log("Deploying from account:", deployer.address);

    const CertificateRegistry = await ethers.getContractFactory(
        "CertificateRegistry"
    );

    const contract = await CertificateRegistry.deploy();

    await contract.waitForDeployment();

    const contractAddress = await contract.getAddress();

    console.log("Certificate Registry deployed!");
    console.log("Contract address:", contractAddress);

    const artifactPath = path.join(
        process.cwd(),
        "artifacts",
        "contracts",
        "CertificateRegistry.sol",
        "CertificateRegistry.json"
    );

    const artifact = JSON.parse(
        fs.readFileSync(artifactPath, "utf8")
    );

    fs.mkdirSync("deployments", { recursive: true });

    fs.writeFileSync(
        "deployments/localhost.json",
        JSON.stringify(
            {
                contractAddress: contractAddress,
                deployer: deployer.address
            },
            null,
            2
        )
    );

    fs.writeFileSync(
        "blockchain/contract_abi.json",
        JSON.stringify(artifact.abi, null, 2)
    );

    console.log("Deployment details saved!");
    console.log("ABI saved!");
}

main().catch((error) => {
    console.error("Deployment failed:", error);
    process.exitCode = 1;
});
