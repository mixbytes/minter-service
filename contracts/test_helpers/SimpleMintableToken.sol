pragma solidity ^0.4.15;

import '../IMintableToken.sol';
import '../IEstimateToken.sol';
import 'zeppelin-solidity/contracts/token/StandardToken.sol';
import 'zeppelin-solidity/contracts/ownership/Ownable.sol';


contract SimpleMintableToken is IMintableToken, StandardToken, Ownable, IEstimateToken {
  
    function mint(address _to, uint256 _amount) onlyOwner {
        totalSupply = totalSupply.add(_amount);
        balances[_to] = balances[_to].add(_amount);
        Transfer(this, _to, _amount);
    }


    function estimate(uint256 _wei) public constant returns (uint256 tokens) {
      return _wei;
    }
    
}
