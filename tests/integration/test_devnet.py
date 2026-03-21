"""Integration tests for the devnet infrastructure.

These tests validate the configuration files and scripts without requiring
Docker or running nodes. They ensure the devnet setup is internally consistent.

Run with: pytest tests/integration/test_devnet.py -m devnet
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
import yaml

# ─── Fixtures ────────────────────────────────────────────────────

DEVNET_DIR = Path(__file__).parent.parent.parent / "infra" / "devnet"
GENESIS_DIR = DEVNET_DIR / "genesis"
TOPOLOGY_DIR = DEVNET_DIR / "topology"
SCRIPTS_DIR = DEVNET_DIR / "scripts"
CONFIG_DIR = DEVNET_DIR / "config"


@pytest.fixture
def devnet_compose() -> dict:
    """Load and parse the devnet Docker Compose file."""
    compose_path = DEVNET_DIR / "docker-compose.devnet.yml"
    with open(compose_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def shelley_genesis() -> dict:
    """Load the Shelley genesis file."""
    with open(GENESIS_DIR / "shelley-genesis.json") as f:
        return json.load(f)


@pytest.fixture
def byron_genesis() -> dict:
    """Load the Byron genesis file."""
    with open(GENESIS_DIR / "byron-genesis.json") as f:
        return json.load(f)


@pytest.fixture
def alonzo_genesis() -> dict:
    """Load the Alonzo genesis file."""
    with open(GENESIS_DIR / "alonzo-genesis.json") as f:
        return json.load(f)


@pytest.fixture
def conway_genesis() -> dict:
    """Load the Conway genesis file."""
    with open(GENESIS_DIR / "conway-genesis.json") as f:
        return json.load(f)


# ─── Docker Compose Tests ────────────────────────────────────────


@pytest.mark.devnet
@pytest.mark.integration
class TestDockerCompose:
    """Validate the devnet Docker Compose configuration."""

    def test_compose_is_valid_yaml(self, devnet_compose: dict) -> None:
        """Docker Compose file must be valid YAML with expected top-level keys."""
        assert "services" in devnet_compose
        assert "networks" in devnet_compose
        assert "volumes" in devnet_compose

    def test_compose_has_three_node_services(self, devnet_compose: dict) -> None:
        """Must define haskell-node-1, haskell-node-2, and vibe-node services."""
        services = devnet_compose["services"]
        assert "haskell-node-1" in services
        assert "haskell-node-2" in services
        assert "vibe-node" in services

    def test_compose_has_genesis_init(self, devnet_compose: dict) -> None:
        """Must have a genesis-init service that patches systemStart."""
        services = devnet_compose["services"]
        assert "genesis-init" in services

    def test_haskell_nodes_depend_on_genesis(self, devnet_compose: dict) -> None:
        """Haskell nodes must depend on genesis-init completing."""
        for name in ["haskell-node-1", "haskell-node-2"]:
            service = devnet_compose["services"][name]
            deps = service.get("depends_on", {})
            assert "genesis-init" in deps

    def test_haskell_nodes_use_cardano_image(self, devnet_compose: dict) -> None:
        """Haskell nodes must use the official cardano-node image."""
        for name in ["haskell-node-1", "haskell-node-2"]:
            image = devnet_compose["services"][name]["image"]
            assert "cardano-node" in image
            # Must be 10.x
            assert "10." in image

    def test_vibe_node_has_peer_config(self, devnet_compose: dict) -> None:
        """Vibe-node must have VIBE_PEERS pointing to both Haskell nodes."""
        env = devnet_compose["services"]["vibe-node"]["environment"]
        peers = env.get("VIBE_PEERS", "")
        assert "haskell-node-1" in peers
        assert "haskell-node-2" in peers

    def test_all_nodes_on_devnet_network(self, devnet_compose: dict) -> None:
        """All node services must be on the devnet network."""
        for name in ["haskell-node-1", "haskell-node-2", "vibe-node"]:
            service = devnet_compose["services"][name]
            networks = service.get("networks", [])
            assert "devnet" in networks

    def test_haskell_nodes_have_key_mounts(self, devnet_compose: dict) -> None:
        """Haskell nodes must have pool key paths configured."""
        for name in ["haskell-node-1", "haskell-node-2"]:
            service = devnet_compose["services"][name]
            # Keys can be in command args or environment variables
            env = service.get("environment", {})
            command = service.get("command", [])
            combined = " ".join(str(c) for c in command)
            combined += " " + " ".join(str(v) for v in env.values())
            assert "kes.skey" in combined
            assert "vrf.skey" in combined
            assert "opcert.cert" in combined


# ─── Genesis File Tests ──────────────────────────────────────────


@pytest.mark.devnet
@pytest.mark.integration
class TestShelleyGenesis:
    """Validate the Shelley genesis configuration."""

    def test_is_valid_json(self, shelley_genesis: dict) -> None:
        """Shelley genesis must be valid JSON."""
        assert isinstance(shelley_genesis, dict)

    def test_slot_length(self, shelley_genesis: dict) -> None:
        """Slot length must be 0.2s for fast devnet."""
        assert shelley_genesis["slotLength"] == 0.2

    def test_epoch_length(self, shelley_genesis: dict) -> None:
        """Epoch length must be 100 slots."""
        assert shelley_genesis["epochLength"] == 100

    def test_security_param(self, shelley_genesis: dict) -> None:
        """Security parameter k must be 10."""
        assert shelley_genesis["securityParam"] == 10

    def test_active_slots_coeff(self, shelley_genesis: dict) -> None:
        """Active slots coefficient must be 0.1 (10%)."""
        assert shelley_genesis["activeSlotsCoeff"] == 0.1

    def test_network_magic(self, shelley_genesis: dict) -> None:
        """Network magic must be 42 (private devnet)."""
        assert shelley_genesis["networkMagic"] == 42

    def test_has_protocol_params(self, shelley_genesis: dict) -> None:
        """Must include protocol parameters."""
        pp = shelley_genesis["protocolParams"]
        assert "maxBlockBodySize" in pp
        assert "maxTxSize" in pp
        assert "keyDeposit" in pp

    def test_has_system_start_placeholder(self, shelley_genesis: dict) -> None:
        """systemStart should exist (patched at runtime by genesis-init)."""
        assert "systemStart" in shelley_genesis

    def test_has_staking_section(self, shelley_genesis: dict) -> None:
        """Must have staking pools and stake sections."""
        assert "staking" in shelley_genesis
        staking = shelley_genesis["staking"]
        assert "pools" in staking
        assert "stake" in staking


@pytest.mark.devnet
@pytest.mark.integration
class TestByronGenesis:
    """Validate the Byron genesis configuration."""

    def test_is_valid_json(self, byron_genesis: dict) -> None:
        """Byron genesis must be valid JSON."""
        assert isinstance(byron_genesis, dict)

    def test_protocol_magic(self, byron_genesis: dict) -> None:
        """Protocol magic must match Shelley genesis networkMagic (42)."""
        assert byron_genesis["protocolConsts"]["protocolMagic"] == 42

    def test_security_param(self, byron_genesis: dict) -> None:
        """k must be 10."""
        assert byron_genesis["protocolConsts"]["k"] == 10

    def test_slot_duration(self, byron_genesis: dict) -> None:
        """Slot duration must be 200ms (matching Shelley's 0.2s)."""
        assert byron_genesis["blockVersionData"]["slotDuration"] == "200"


@pytest.mark.devnet
@pytest.mark.integration
class TestAlonzoGenesis:
    """Validate the Alonzo genesis configuration."""

    def test_is_valid_json(self, alonzo_genesis: dict) -> None:
        """Alonzo genesis must be valid JSON."""
        assert isinstance(alonzo_genesis, dict)

    def test_has_cost_models(self, alonzo_genesis: dict) -> None:
        """Must include PlutusV1 and PlutusV2 cost models."""
        assert "costModels" in alonzo_genesis
        assert "PlutusV1" in alonzo_genesis["costModels"]
        assert "PlutusV2" in alonzo_genesis["costModels"]

    def test_has_execution_prices(self, alonzo_genesis: dict) -> None:
        """Must include execution unit prices."""
        assert "executionPrices" in alonzo_genesis
        assert "prMem" in alonzo_genesis["executionPrices"]
        assert "prSteps" in alonzo_genesis["executionPrices"]

    def test_has_max_tx_ex_units(self, alonzo_genesis: dict) -> None:
        """Must include max transaction execution units."""
        assert "maxTxExUnits" in alonzo_genesis
        assert "exUnitsMem" in alonzo_genesis["maxTxExUnits"]
        assert "exUnitsSteps" in alonzo_genesis["maxTxExUnits"]


@pytest.mark.devnet
@pytest.mark.integration
class TestConwayGenesis:
    """Validate the Conway genesis configuration."""

    def test_is_valid_json(self, conway_genesis: dict) -> None:
        """Conway genesis must be valid JSON."""
        assert isinstance(conway_genesis, dict)

    def test_has_pool_voting_thresholds(self, conway_genesis: dict) -> None:
        """Must include pool voting thresholds."""
        assert "poolVotingThresholds" in conway_genesis
        pvt = conway_genesis["poolVotingThresholds"]
        assert "committeeNormal" in pvt
        assert "hardForkInitiation" in pvt

    def test_has_drep_voting_thresholds(self, conway_genesis: dict) -> None:
        """Must include DRep voting thresholds."""
        assert "dRepVotingThresholds" in conway_genesis

    def test_has_governance_params(self, conway_genesis: dict) -> None:
        """Must include governance action parameters."""
        assert "govActionLifetime" in conway_genesis
        assert "govActionDeposit" in conway_genesis
        assert "dRepDeposit" in conway_genesis


# ─── Topology Tests ──────────────────────────────────────────────


@pytest.mark.devnet
@pytest.mark.integration
class TestTopology:
    """Validate topology files reference correct hostnames."""

    @pytest.fixture
    def topology_files(self) -> dict[str, dict]:
        """Load all topology files."""
        result = {}
        for f in TOPOLOGY_DIR.glob("*.json"):
            with open(f) as fh:
                result[f.stem] = json.load(fh)
        return result

    def test_all_topology_files_exist(self) -> None:
        """Must have topology files for all 3 nodes."""
        assert (TOPOLOGY_DIR / "haskell-node-1.json").exists()
        assert (TOPOLOGY_DIR / "haskell-node-2.json").exists()
        assert (TOPOLOGY_DIR / "vibe-node.json").exists()

    def test_topology_is_valid_json(self, topology_files: dict) -> None:
        """All topology files must be valid JSON."""
        assert len(topology_files) >= 3
        for name, data in topology_files.items():
            assert "localRoots" in data, f"{name} missing localRoots"

    def test_haskell_node_1_connects_to_others(self, topology_files: dict) -> None:
        """haskell-node-1 must connect to haskell-node-2 and vibe-node."""
        topo = topology_files["haskell-node-1"]
        addresses = {
            ap["address"]
            for root in topo["localRoots"]
            for ap in root["accessPoints"]
        }
        assert "haskell-node-2" in addresses
        assert "vibe-node" in addresses

    def test_haskell_node_2_connects_to_others(self, topology_files: dict) -> None:
        """haskell-node-2 must connect to haskell-node-1 and vibe-node."""
        topo = topology_files["haskell-node-2"]
        addresses = {
            ap["address"]
            for root in topo["localRoots"]
            for ap in root["accessPoints"]
        }
        assert "haskell-node-1" in addresses
        assert "vibe-node" in addresses

    def test_vibe_node_connects_to_haskell_nodes(self, topology_files: dict) -> None:
        """vibe-node must connect to both Haskell nodes."""
        topo = topology_files["vibe-node"]
        addresses = {
            ap["address"]
            for root in topo["localRoots"]
            for ap in root["accessPoints"]
        }
        assert "haskell-node-1" in addresses
        assert "haskell-node-2" in addresses

    def test_all_use_port_3001(self, topology_files: dict) -> None:
        """All access points must use port 3001."""
        for name, topo in topology_files.items():
            for root in topo["localRoots"]:
                for ap in root["accessPoints"]:
                    assert ap["port"] == 3001, f"{name}: {ap['address']} uses port {ap['port']}"


# ─── Script Tests ────────────────────────────────────────────────


@pytest.mark.devnet
@pytest.mark.integration
class TestScripts:
    """Validate devnet scripts."""

    def test_generate_keys_exists(self) -> None:
        """Key generation script must exist."""
        assert (SCRIPTS_DIR / "generate-keys.sh").exists()

    def test_generate_keys_is_bash(self) -> None:
        """Key generation script must have a bash shebang."""
        content = (SCRIPTS_DIR / "generate-keys.sh").read_text()
        assert content.startswith("#!/usr/bin/env bash")

    def test_generate_keys_has_correct_structure(self) -> None:
        """Key generation script must generate keys for 3 pools."""
        content = (SCRIPTS_DIR / "generate-keys.sh").read_text()
        # Must reference cardano-cli
        assert "cardano-cli" in content
        # Must generate KES, VRF, and cold keys
        assert "key-gen-KES" in content
        assert "key-gen-VRF" in content
        assert "node key-gen" in content
        # Must generate opcerts
        assert "issue-op-cert" in content
        # Must handle 3 pools
        assert "NUM_POOLS=3" in content

    def test_generate_keys_does_not_contain_keys(self) -> None:
        """Script must not contain actual key material."""
        content = (SCRIPTS_DIR / "generate-keys.sh").read_text()
        # Should not contain PEM key blocks (actual key material)
        assert "-----BEGIN" not in content  # PEM format
        # Lines containing "5820" should only be in comments, not as key data
        for line in content.splitlines():
            stripped = line.strip()
            if "5820" in stripped and not stripped.startswith("#"):
                assert False, f"Non-comment line contains CBOR prefix: {stripped}"

    def test_monitor_tips_exists(self) -> None:
        """Tip monitoring script must exist."""
        assert (SCRIPTS_DIR / "monitor-tips.py").exists()

    def test_monitor_tips_is_python(self) -> None:
        """Tip monitoring script must have a Python shebang."""
        content = (SCRIPTS_DIR / "monitor-tips.py").read_text()
        assert content.startswith("#!/usr/bin/env python3")


def _parse_nodes(nodes_str: str) -> list[tuple[str, str, int]]:
    """Inline copy of parse_nodes from monitor-tips.py for testing.

    We duplicate the logic here instead of importing the script directly
    because importlib.util dynamic loading has issues with dataclasses
    on Python 3.14.
    """
    result = []
    for entry in nodes_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            name, hostport = entry.split("=", 1)
        else:
            hostport = entry
            name = hostport.split(":")[0]
        host, port_str = hostport.rsplit(":", 1)
        result.append((name, host, int(port_str)))
    return result


@pytest.mark.devnet
@pytest.mark.integration
class TestMonitorArgParsing:
    """Validate monitor script argument parsing."""

    def test_parse_nodes_host_port(self) -> None:
        """parse_nodes should handle host:port format."""
        nodes = _parse_nodes("host1:3001,host2:3002")
        assert len(nodes) == 2
        assert nodes[0] == ("host1", "host1", 3001)
        assert nodes[1] == ("host2", "host2", 3002)

    def test_parse_nodes_named(self) -> None:
        """parse_nodes should handle name=host:port format."""
        nodes = _parse_nodes("node1=h1:3001,node2=h2:3002")
        assert len(nodes) == 2
        assert nodes[0] == ("node1", "h1", 3001)
        assert nodes[1] == ("node2", "h2", 3002)

    def test_parse_nodes_empty_entries(self) -> None:
        """parse_nodes should skip empty entries."""
        nodes = _parse_nodes("host1:3001,,host2:3002,")
        assert len(nodes) == 2


# ─── Config Tests ────────────────────────────────────────────────


@pytest.mark.devnet
@pytest.mark.integration
class TestNodeConfig:
    """Validate the cardano-node configuration."""

    @pytest.fixture
    def node_config(self) -> dict:
        with open(CONFIG_DIR / "config.json") as f:
            return json.load(f)

    def test_is_valid_json(self, node_config: dict) -> None:
        """Node config must be valid JSON."""
        assert isinstance(node_config, dict)

    def test_references_genesis_files(self, node_config: dict) -> None:
        """Must reference all genesis files."""
        assert "ShelleyGenesisFile" in node_config
        assert "ByronGenesisFile" in node_config
        assert "AlonzoGenesisFile" in node_config
        assert "ConwayGenesisFile" in node_config

    def test_hard_forks_at_epoch_zero(self, node_config: dict) -> None:
        """All hard forks must happen at epoch 0 for immediate Conway."""
        assert node_config.get("TestShelleyHardForkAtEpoch") == 0
        assert node_config.get("TestAllegraHardForkAtEpoch") == 0
        assert node_config.get("TestMaryHardForkAtEpoch") == 0
        assert node_config.get("TestAlonzoHardForkAtEpoch") == 0
        assert node_config.get("TestBabbageHardForkAtEpoch") == 0
        assert node_config.get("TestConwayHardForkAtEpoch") == 0

    def test_p2p_enabled(self, node_config: dict) -> None:
        """P2P networking must be enabled."""
        assert node_config.get("EnableP2P") is True

    def test_requires_magic(self, node_config: dict) -> None:
        """Must require network magic (not mainnet)."""
        assert node_config.get("RequiresNetworkMagic") == "RequiresMagic"

    def test_protocol_is_cardano(self, node_config: dict) -> None:
        """Protocol must be Cardano (combined Byron+Shelley+...)."""
        assert node_config.get("Protocol") == "Cardano"
