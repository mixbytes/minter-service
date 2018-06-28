pragma solidity ^0.4.15;

contract IICOInfo {
  function estimate(uint256 _wei) public constant returns (uint tokens);
  function purchasedTokenBalanceOf(address addr) public constant returns (uint256 tokens);
  function sentEtherBalanceOf(address addr) public constant returns (uint256 _wei);

  function getNonEtherController() public constant returns (address);

   /// @notice minimum investment in cents
    uint public c_MinInvestmentInCents = 10000; // $100




    /// @dev address receiving all the ether, no intentions to refund
    address public m_beneficiary;

    /// @dev next sale to receive remaining tokens after this one finishes
    address public m_nextSale;

    /// @dev active sale can accept ether, inactive - cannot
    bool public m_active;

    /**
     *  @dev unix timestamp that sets preICO finish date, which means that after that date
     *       you cannot buy anything, but finish can happen before, if owners decide to do so
     */
    uint public c_dateTo = 1532563200; // 26-Jul-18 00:00:00 UTC

    /// @dev current amount of tokens sold
    uint public m_currentTokensSold = 0;
    /// @dev limit of tokens to be sold during presale
    uint public c_maximumTokensSold = uint(5000000) * uint(10) ** uint(18); // 5 million tokens

    /// @notice usd price of BoomstarterToken in cents 
    uint public c_centsPerToken = 60; // $0.6

      /// @notice usd price of ETH in cents, retrieved using oraclize
    uint public m_ETHPriceInCents = 0;
    /// @notice unix timestamp of last update
    uint public m_ETHPriceLastUpdate;
    /// @notice unix timestamp of last update request,
    ///         don't allow requesting more than once per update interval
    uint public m_ETHPriceLastUpdateRequest;

    /// @notice lower bound of the ETH price in cents
    uint public m_ETHPriceLowerBound = 100;
    /// @notice upper bound of the ETH price in cents
    uint public m_ETHPriceUpperBound = 100000000;

    /// @dev Update ETH price in cents every 12 hours
    uint public m_ETHPriceUpdateInterval = 60*60*12;

    /// @dev offset time inaccuracy when checking update expiration date
    uint public m_leeway = 900; // 15 minutes is the limit for miners

    /// @dev set just enough gas because the rest is not refunded
    uint public m_callbackGas = 200000;
}
