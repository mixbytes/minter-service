pragma solidity ^0.4.15;

contract IICOInfo {
  function estimate(uint256 _wei) public constant returns (uint tokens);
  function tokenBalanceOf(address addr) public constant returns (uint256 tokens);
  function etherFundsOf(address addr) public constant returns (uint256 _wei);  
}
