// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC1155} from "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/**
 * @title CarbonGuard
 * @notice AI-gated, double-counting-proof carbon credits.
 *
 * Each token id is one project-vintage batch bridged from an off-chain registry
 * (Verra, Gold Standard, ACR, CAR). One token = one tonne of CO2e.
 *
 * Three kinds of double counting are blocked:
 *   1. Double tokenisation - a registry serial range can only be bridged once;
 *      even a partial overlap with an existing range reverts.
 *   2. Double selling     - credits are burned on retirement, so a retired
 *      tonne can never be transferred or retired again.
 *   3. Double claiming    - credits can only back a compliance / NDC claim if
 *      the host country applied a Paris Agreement Article 6 corresponding
 *      adjustment.
 *
 * Quality gate: an off-chain AI model (see /ai) scores every batch. The score,
 * the human-readable reasons, and the SHA-256 of the model and of its input
 * data are written on chain by an ORACLE. High-risk batches (> 70) are frozen
 * until independent human VERIFIERs approve or reject them: a decision needs
 * `requiredApprovals` matching votes (e.g. 2-of-3), so no single key can
 * unfreeze junk credits.
 */
contract CarbonGuard is ERC1155, AccessControl {
    bytes32 public constant REGISTRY_ROLE = keccak256("REGISTRY_ROLE");
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER_ROLE");
    uint8 public constant HIGH_RISK_THRESHOLD = 70;

    enum Status {
        Pending, // bridged, waiting for an AI risk score - not tradable
        Active, // scored low/medium risk or approved by a verifier - tradable
        Flagged, // AI scored high risk - frozen until human review
        Rejected // verifier confirmed the flag - permanently frozen
    }

    struct BatchInput {
        string registry; // e.g. "VCS"
        string projectId; // e.g. "VCS1389"
        string projectType; // e.g. "REDD+"
        string country;
        uint16 vintage;
        uint256 serialFrom; // first registry serial number (inclusive)
        uint256 serialTo; // last registry serial number (inclusive)
        bool correspondingAdjustment; // Article 6 CA applied by host country
    }

    struct Batch {
        string registry;
        string projectId;
        string projectType;
        string country;
        uint16 vintage;
        uint256 serialFrom;
        uint256 serialTo;
        bool correspondingAdjustment;
        Status status;
        bool humanReviewed;
        uint8 riskScore;
        string riskReasons;
        bytes32 modelHash;
        bytes32 dataHash;
        uint64 scoredAt;
        uint256 issued;
        uint256 retired;
    }

    struct Retirement {
        uint256 tokenId;
        address retiree;
        string beneficiary;
        string purpose;
        uint256 amount;
        bool complianceClaim;
        uint8 riskScoreAtRetirement;
        bytes32 modelHash;
        uint64 timestamp;
    }

    struct Votes {
        uint8 approvals;
        uint8 rejections;
    }

    struct SerialRange {
        uint256 from;
        uint256 to;
        uint256 tokenId;
    }

    uint256 public batchCount;
    uint256 public totalIssued;
    uint256 public totalRetired;
    /// @notice Matching verifier votes needed to approve or reject a flagged batch.
    uint8 public requiredApprovals = 1;
    mapping(uint256 => Batch) private _batches;
    Retirement[] private _retirements;
    // keccak256(registry, projectId, vintage) => serial ranges already bridged
    mapping(bytes32 => SerialRange[]) private _ranges;
    mapping(uint256 => Votes) private _votes;
    mapping(uint256 => mapping(address => bool)) private _hasVoted;

    event BatchRegistered(
        uint256 indexed tokenId,
        string registry,
        string projectId,
        uint16 vintage,
        uint256 serialFrom,
        uint256 serialTo,
        address indexed owner
    );
    event RiskScored(
        uint256 indexed tokenId, uint8 score, Status status, string reasons, bytes32 modelHash, bytes32 dataHash
    );
    event VerifierVote(uint256 indexed tokenId, address indexed verifier, bool approve, string note);
    event VerifierDecision(uint256 indexed tokenId, bool approved, string note, address indexed verifier);
    event RequiredApprovalsChanged(uint8 required);
    event Retired(
        uint256 indexed retirementId,
        uint256 indexed tokenId,
        address indexed retiree,
        string beneficiary,
        uint256 amount,
        bool complianceClaim,
        uint8 riskScore
    );

    error UnknownBatch(uint256 tokenId);
    error InvalidSerialRange();
    error AlreadyTokenized(uint256 existingTokenId, uint256 overlapFrom, uint256 overlapTo);
    error ScoreOutOfRange(uint8 score);
    error AlreadyReviewed(uint256 tokenId);
    error NotFlagged(uint256 tokenId, Status status);
    error NotTradable(uint256 tokenId, Status status);
    error ZeroAmount();
    error NoCorrespondingAdjustment(uint256 tokenId);
    error AlreadyVoted(uint256 tokenId, address verifier);
    error InvalidThreshold();

    constructor(address admin) ERC1155("") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(REGISTRY_ROLE, admin);
        _grantRole(ORACLE_ROLE, admin);
        _grantRole(VERIFIER_ROLE, admin);
    }

    // ------------------------------------------------------------------ registry

    /// @notice Bridge a registry serial range on chain. Amount = number of serials.
    function registerBatch(BatchInput calldata b, address owner)
        external
        onlyRole(REGISTRY_ROLE)
        returns (uint256 tokenId)
    {
        if (b.serialTo < b.serialFrom || owner == address(0)) revert InvalidSerialRange();

        bytes32 key = keccak256(abi.encode(b.registry, b.projectId, b.vintage));
        SerialRange[] storage existing = _ranges[key];
        for (uint256 i = 0; i < existing.length; i++) {
            SerialRange memory r = existing[i];
            if (b.serialFrom <= r.to && r.from <= b.serialTo) {
                revert AlreadyTokenized(
                    r.tokenId, b.serialFrom > r.from ? b.serialFrom : r.from, b.serialTo < r.to ? b.serialTo : r.to
                );
            }
        }

        tokenId = ++batchCount;
        uint256 amount = b.serialTo - b.serialFrom + 1;
        existing.push(SerialRange(b.serialFrom, b.serialTo, tokenId));

        Batch storage batch = _batches[tokenId];
        batch.registry = b.registry;
        batch.projectId = b.projectId;
        batch.projectType = b.projectType;
        batch.country = b.country;
        batch.vintage = b.vintage;
        batch.serialFrom = b.serialFrom;
        batch.serialTo = b.serialTo;
        batch.correspondingAdjustment = b.correspondingAdjustment;
        batch.issued = amount;
        totalIssued += amount;

        emit BatchRegistered(tokenId, b.registry, b.projectId, b.vintage, b.serialFrom, b.serialTo, owner);
        _mint(owner, tokenId, amount, "");
    }

    /// @notice Human-in-the-loop review of a batch the AI flagged. Each verifier
    /// votes once; the batch is unfrozen (or permanently rejected) as soon as
    /// `requiredApprovals` verifiers agree.
    function verifierDecision(uint256 tokenId, bool approve, string calldata note) external onlyRole(VERIFIER_ROLE) {
        Batch storage batch = _batch(tokenId);
        if (batch.status != Status.Flagged) revert NotFlagged(tokenId, batch.status);
        if (_hasVoted[tokenId][msg.sender]) revert AlreadyVoted(tokenId, msg.sender);
        _hasVoted[tokenId][msg.sender] = true;

        Votes storage v = _votes[tokenId];
        uint8 count = approve ? ++v.approvals : ++v.rejections;
        emit VerifierVote(tokenId, msg.sender, approve, note);
        if (count >= requiredApprovals) {
            batch.status = approve ? Status.Active : Status.Rejected;
            batch.humanReviewed = true;
            emit VerifierDecision(tokenId, approve, note, msg.sender);
        }
    }

    /// @notice Set how many matching verifier votes a decision needs (e.g. 2 for 2-of-3).
    function setRequiredApprovals(uint8 required) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (required == 0) revert InvalidThreshold();
        requiredApprovals = required;
        emit RequiredApprovalsChanged(required);
    }

    // -------------------------------------------------------------------- oracle

    /// @notice Record an AI risk score with full model provenance.
    /// Re-scoring with a newer model can freeze an active batch, unless a human
    /// verifier has already reviewed it (human decision is final). The AI can
    /// only tighten: a Flagged batch stays frozen until a verifier decides.
    function setRiskScore(
        uint256 tokenId,
        uint8 score,
        string calldata reasons,
        bytes32 modelHash,
        bytes32 dataHash
    ) external onlyRole(ORACLE_ROLE) {
        if (score > 100) revert ScoreOutOfRange(score);
        Batch storage batch = _batch(tokenId);
        if (batch.status == Status.Rejected) revert AlreadyReviewed(tokenId);

        batch.riskScore = score;
        batch.riskReasons = reasons;
        batch.modelHash = modelHash;
        batch.dataHash = dataHash;
        batch.scoredAt = uint64(block.timestamp);
        if (!batch.humanReviewed && batch.status != Status.Flagged) {
            batch.status = score > HIGH_RISK_THRESHOLD ? Status.Flagged : Status.Active;
        }
        emit RiskScored(tokenId, score, batch.status, reasons, modelHash, dataHash);
    }

    // --------------------------------------------------------------- retirement

    /// @notice Permanently retire (burn) credits on behalf of a beneficiary.
    /// @param complianceClaim true if the credits back an NDC / CORSIA / compliance
    ///        claim - only allowed when an Article 6 corresponding adjustment exists.
    function retire(
        uint256 tokenId,
        uint256 amount,
        string calldata beneficiary,
        string calldata purpose,
        bool complianceClaim
    ) external returns (uint256 retirementId) {
        if (amount == 0) revert ZeroAmount();
        Batch storage batch = _batch(tokenId);
        if (complianceClaim && !batch.correspondingAdjustment) revert NoCorrespondingAdjustment(tokenId);

        _burn(msg.sender, tokenId, amount); // reverts if not Active or balance too low
        batch.retired += amount;
        totalRetired += amount;

        retirementId = _retirements.length;
        _retirements.push(
            Retirement({
                tokenId: tokenId,
                retiree: msg.sender,
                beneficiary: beneficiary,
                purpose: purpose,
                amount: amount,
                complianceClaim: complianceClaim,
                riskScoreAtRetirement: batch.riskScore,
                modelHash: batch.modelHash,
                timestamp: uint64(block.timestamp)
            })
        );
        emit Retired(retirementId, tokenId, msg.sender, beneficiary, amount, complianceClaim, batch.riskScore);
    }

    // --------------------------------------------------------------------- views

    function getBatch(uint256 tokenId) external view returns (Batch memory) {
        return _batch(tokenId);
    }

    function retirementCount() external view returns (uint256) {
        return _retirements.length;
    }

    function getRetirement(uint256 retirementId) external view returns (Retirement memory) {
        return _retirements[retirementId];
    }

    function getVotes(uint256 tokenId) external view returns (uint8 approvals, uint8 rejections, uint8 required) {
        _batch(tokenId);
        Votes storage v = _votes[tokenId];
        return (v.approvals, v.rejections, requiredApprovals);
    }

    function hasVoted(uint256 tokenId, address verifier) external view returns (bool) {
        return _hasVoted[tokenId][verifier];
    }

    function isTradable(uint256 tokenId) public view returns (bool) {
        return _batch(tokenId).status == Status.Active;
    }

    // ------------------------------------------------------------------ internals

    function _batch(uint256 tokenId) internal view returns (Batch storage batch) {
        if (tokenId == 0 || tokenId > batchCount) revert UnknownBatch(tokenId);
        return _batches[tokenId];
    }

    /// @dev Quality gate on every movement except the initial mint: transfers
    /// and retirements (burns) require the batch to be Active.
    function _update(address from, address to, uint256[] memory ids, uint256[] memory values) internal override {
        if (from != address(0)) {
            for (uint256 i = 0; i < ids.length; i++) {
                Status s = _batches[ids[i]].status;
                if (s != Status.Active) revert NotTradable(ids[i], s);
            }
        }
        super._update(from, to, ids, values);
    }

    function supportsInterface(bytes4 interfaceId) public view override(ERC1155, AccessControl) returns (bool) {
        return super.supportsInterface(interfaceId);
    }
}
