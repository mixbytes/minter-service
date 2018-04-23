pragma solidity ^0.4.15;

contract IEstimateToken {
  function estimate(uint256 _wei) public constant returns (uint tokens);
}
