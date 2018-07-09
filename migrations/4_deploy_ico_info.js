var SimpleMintableToken = artifacts.require("./test_helpers/SimpleMintableToken.sol");
var IMintableToken = artifacts.require("./IMintableToken.sol");
var ReenterableMinter = artifacts.require("./ReenterableMinter.sol");
var MockMinterCompatibleICO = artifacts.require("./example/MockMinterCompatibleICO.sol");
var mintableTokenAddress = process.env.TOKEN_ADDRESS


module.exports = function(deployer) {
   deployer
    .then( function() {
        if (mintableTokenAddress == null) {
            return SimpleMintableToken.deployed();
        } else {
            return mintableTokenAddress
        }
    })
    .then( function(token) {
      instanceMintableToken = token;
      return deployer.deploy(MockMinterCompatibleICO, instanceMintableToken)
    })
};
