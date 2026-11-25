
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract CertificateRegistry {

    struct Certificate {
        string certificateId;
        string certificateHash;
        address issuer;
        uint256 timestamp;
        bool exists;
    }

    mapping(string => Certificate) private certificates;

    event CertificateRegistered(
        string certificateId,
        string certificateHash,
        address issuer,
        uint256 timestamp
    );

    function registerCertificate(
        string memory _certificateId,
        string memory _certificateHash
    ) public {
        require(bytes(_certificateId).length > 0, "Invalid certificate ID");
        require(bytes(_certificateHash).length > 0, "Invalid certificate hash");
        require(!certificates[_certificateId].exists, "Certificate already registered");

        certificates[_certificateId] = Certificate(
            _certificateId,
            _certificateHash,
            msg.sender,
            block.timestamp,
            true
        );

        emit CertificateRegistered(
            _certificateId,
            _certificateHash,
            msg.sender,
            block.timestamp
        );
    }

    function verifyCertificate(
        string memory _certificateId
    ) public view returns (
        string memory certificateHash,
        address issuer,
        uint256 timestamp,
        bool exists
    ) {
        Certificate memory cert = certificates[_certificateId];

        return (
            cert.certificateHash,
            cert.issuer,
            cert.timestamp,
            cert.exists
        );
    }
}
