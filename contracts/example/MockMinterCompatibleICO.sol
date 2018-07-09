pragma solidity ^0.4.0;

pragma solidity ^0.4.15;

import '../IMintableToken.sol';
import '../IICOInfo.sol';
import 'zeppelin-solidity/contracts/ownership/Ownable.sol';


contract MockMinterCompatibleICO is Ownable, IICOInfo {
    event MintSuccess(bytes32 indexed mint_id);

    function MockMinterCompatibleICO(IMintableToken token){
        m_token = token;
    }

    function mint(bytes32 mint_id, address to, uint256 amount) onlyOwner {
        // Not reverting because there will be no way to distinguish this revert from other transaction failures.
        if (!m_processed_mint_id[mint_id]) {
            m_token.mint(to, amount);
            m_processed_mint_id[mint_id] = true;
            balance[to] = balance[to] + amount;
        }
        MintSuccess(mint_id);
    }

    IMintableToken public m_token;

    mapping(bytes32 => bool) public m_processed_mint_id;
    mapping(address => uint256) public balance;
    mapping(address => uint256) public etherBalance;

    function estimate(uint256 _wei) public constant returns (uint tokens) {
        return _wei;
    }
    function purchasedTokenBalanceOf(address addr) public constant returns (uint256 tokens) {
        return balance[addr];
    }
    function sentEtherBalanceOf(address addr) public constant returns (uint256 _wei) {
        return etherBalance[addr];
    }

    function isSaleActive() public constant returns (bool active) {
        return true;
    }
                                                                 

    function() payable {
        etherBalance[msg.sender] = etherBalance[msg.sender] + msg.value;
        balance[msg.sender] = balance[msg.sender] + msg.value;
        m_token.mint(msg.sender, msg.value);
    }
}
