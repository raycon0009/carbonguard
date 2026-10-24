// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {CarbonGuard} from "./CarbonGuard.sol";

/**
 * @title CarbonMarket
 * @notice Example marketplace for CarbonGuard credits: fixed-price listings
 * paid in ETH. It shows how any trading venue inherits CarbonGuard's quality
 * gate:
 *   - credits that are not tradable (pending, flagged or rejected) cannot be
 *     listed;
 *   - a listing whose credits are frozen AFTER listing (e.g. a new satellite
 *     measurement re-scores the batch) is suspended: it cannot be bought until
 *     human verifiers approve the batch again;
 *   - even without these checks, CarbonGuard's own transfer gate would revert.
 *
 * Sellers keep custody until a sale (no escrow), so credits frozen while
 * listed never get stuck in the market. Sellers collect ETH with withdraw().
 */
contract CarbonMarket is ReentrancyGuard {
    struct Listing {
        address seller;
        uint256 tokenId;
        uint256 remaining; // tonnes still for sale
        uint256 pricePerTonne; // wei
        bool open;
    }

    CarbonGuard public immutable carbonGuard;
    Listing[] private _listings;
    mapping(address => uint256) public proceeds;

    event Listed(uint256 indexed listingId, address indexed seller, uint256 indexed tokenId, uint256 amount, uint256 pricePerTonne);
    event Purchased(uint256 indexed listingId, address indexed buyer, uint256 amount, uint256 paid);
    event Cancelled(uint256 indexed listingId);
    event Withdrawn(address indexed seller, uint256 amount);

    error CreditsFrozen(uint256 tokenId);
    error ZeroAmount();
    error MarketNotApproved();
    error InsufficientBalance(uint256 balance, uint256 amount);
    error ListingClosed(uint256 listingId);
    error InsufficientListing(uint256 remaining, uint256 amount);
    error WrongPayment(uint256 expected, uint256 sent);
    error NotSeller();
    error NothingToWithdraw();
    error WithdrawFailed();

    constructor(CarbonGuard carbonGuard_) {
        carbonGuard = carbonGuard_;
    }

    /// @notice List credits for sale. The seller must first call
    /// carbonGuard.setApprovalForAll(market, true).
    function list(uint256 tokenId, uint256 amount, uint256 pricePerTonne) external returns (uint256 listingId) {
        if (amount == 0 || pricePerTonne == 0) revert ZeroAmount();
        if (!carbonGuard.isTradable(tokenId)) revert CreditsFrozen(tokenId);
        if (!carbonGuard.isApprovedForAll(msg.sender, address(this))) revert MarketNotApproved();
        uint256 balance = carbonGuard.balanceOf(msg.sender, tokenId);
        if (balance < amount) revert InsufficientBalance(balance, amount);

        listingId = _listings.length;
        _listings.push(Listing(msg.sender, tokenId, amount, pricePerTonne, true));
        emit Listed(listingId, msg.sender, tokenId, amount, pricePerTonne);
    }

    /// @notice Buy `amount` tonnes from a listing. Pay exactly amount x price.
    function buy(uint256 listingId, uint256 amount) external payable nonReentrant {
        Listing storage l = _listing(listingId);
        if (!l.open) revert ListingClosed(listingId);
        if (amount == 0) revert ZeroAmount();
        if (amount > l.remaining) revert InsufficientListing(l.remaining, amount);
        // Re-checked at purchase time: the batch may have been frozen since listing.
        if (!carbonGuard.isTradable(l.tokenId)) revert CreditsFrozen(l.tokenId);
        uint256 cost = amount * l.pricePerTonne;
        if (msg.value != cost) revert WrongPayment(cost, msg.value);

        l.remaining -= amount;
        if (l.remaining == 0) l.open = false;
        proceeds[l.seller] += cost;
        emit Purchased(listingId, msg.sender, amount, cost);
        carbonGuard.safeTransferFrom(l.seller, msg.sender, l.tokenId, amount, "");
    }

    function cancel(uint256 listingId) external {
        Listing storage l = _listing(listingId);
        if (msg.sender != l.seller) revert NotSeller();
        if (!l.open) revert ListingClosed(listingId);
        l.open = false;
        emit Cancelled(listingId);
    }

    /// @notice Sellers collect their sale proceeds (pull payment).
    function withdraw() external nonReentrant {
        uint256 amount = proceeds[msg.sender];
        if (amount == 0) revert NothingToWithdraw();
        proceeds[msg.sender] = 0;
        emit Withdrawn(msg.sender, amount);
        (bool ok,) = payable(msg.sender).call{value: amount}("");
        if (!ok) revert WithdrawFailed();
    }

    // --------------------------------------------------------------------- views

    function listingCount() external view returns (uint256) {
        return _listings.length;
    }

    function getListing(uint256 listingId) external view returns (Listing memory) {
        return _listing(listingId);
    }

    /// @notice True when the listing can be bought right now: open, and its
    /// credits are still tradable. A false here on an open listing means
    /// "suspended: credits frozen by CarbonGuard".
    function isLive(uint256 listingId) external view returns (bool) {
        Listing storage l = _listing(listingId);
        return l.open && carbonGuard.isTradable(l.tokenId);
    }

    function _listing(uint256 listingId) internal view returns (Listing storage) {
        if (listingId >= _listings.length) revert ListingClosed(listingId);
        return _listings[listingId];
    }
}
