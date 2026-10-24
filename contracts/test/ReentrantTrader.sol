// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {CarbonGuard} from "../CarbonGuard.sol";
import {CarbonMarket} from "../CarbonMarket.sol";

/// @dev Test-only attacker: tries to re-enter the market while it is paying
/// out (as a seller) or delivering credits (as a buyer).
contract ReentrantTrader {
    CarbonMarket public immutable market;
    CarbonGuard public immutable cg;
    uint256 public targetListing;
    bool public attacking;

    constructor(CarbonMarket market_) {
        market = market_;
        cg = market_.carbonGuard();
    }

    function listAll(uint256 tokenId, uint256 amount, uint256 price) external {
        cg.setApprovalForAll(address(market), true);
        targetListing = market.list(tokenId, amount, price);
    }

    function buy(uint256 listingId, uint256 amount) external payable {
        targetListing = listingId;
        attacking = true;
        market.buy{value: msg.value}(listingId, amount);
        attacking = false;
    }

    function withdraw() external {
        attacking = true;
        market.withdraw();
        attacking = false;
    }

    // Credits arrive: try to buy again before the first purchase finishes.
    function onERC1155Received(address, address, uint256, uint256, bytes calldata) external returns (bytes4) {
        if (attacking) market.buy{value: 0}(targetListing, 1);
        return this.onERC1155Received.selector;
    }

    // ETH arrives: try to withdraw again.
    receive() external payable {
        if (attacking) market.withdraw();
    }
}
