# Cardano Node Configuration

The cardano-node service requires network-specific configuration files. These are
obtained via the Mithril snapshot download or can be placed manually.

## Preprod

Download configuration files from:
https://book.play.dev.cardano.org/env-preprod/

Required files:
- `config.json`
- `topology.json`
- `byron-genesis.json`
- `shelley-genesis.json`
- `alonzo-genesis.json`
- `conway-genesis.json`

## Mainnet

Download configuration files from:
https://book.play.dev.cardano.org/env-mainnet/

Same file set as above, with mainnet-specific values.

## Notes

- The Mithril client downloads these as part of the snapshot process
- Configuration files end up in the `cardano-node-data` Docker volume at `/data/`
- The cardano-node and Ogmios services expect `config.json` at `/data/config.json`
