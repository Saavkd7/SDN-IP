# SDN-IP Network with MCS

# Minimum Candidate Selection (MCS) for Hybrid IP/SDN Networks

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Mininet](https://img.shields.io/badge/Mininet-2.3.0-green)](http://mininet.org/)
[![NetworkX](https://img.shields.io/badge/NetworkX-Graph%20Theory-red)](https://networkx.org/)

## 📄 Abstract

This repository contains a Python and Mininet implementation of the **Minimum Candidate Selection (MCS)** algorithm, as proposed in the paper:

> **"Minimum Candidate Selection Algorithm for Hybrid IP/SDN Networks With Single Link Failures"**
> *Navya Vuppalapati and T.G. Venkatesh, IEEE Networking Letters, 2022.*

### The Problem
Transitioning fully from legacy IP networks to Software Defined Networks (SDN) is cost-prohibitive. A **Hybrid IP/SDN** architecture offers a middle ground, upgrading only specific routers to SDN switches. The challenge is identifying the *minimum* set of routers to upgrade (Candidates) to ensure the network can recover from any **Single Link Failure (SLF)**.

### The Solution: MCS Algorithm
The MCS algorithm implemented here:
1.  Analyzes the network topology (Abilene).
2.  Identifies "Affected Destinations" for every possible link failure.
3.  Constructs a Candidate Table to determine which nodes can act as recovery points.
4.  Uses combinatorial logic to find the **globally minimum** set of SDN switches required to cover 100% of failures.
5.  Optimizes for **Average Repair Path Length (ARPL)**.

---

## 🏗 System Model: The Abilene Topology

This implementation utilizes the **Abilene Network** topology (Internet2) as the primary testbed, consistent with the simulation results presented in Section V of the paper.

![Abilene](assets/AbileneTopo.png)


* **Graph:** $G = (V, E)$
* **Nodes:** 11 Major US Cities (ATLA, CHIN, DNVR, HSTN, IPLS, KSCY, LOSA, NYCM, SNVA, STTL, WASH).
* **Links:** OC-192 and OC-48 connections with realistic propagation delays.

---

## 📂 Project Structure

This repository is divided into the **Analytical Plane** (Algorithm Logic), the **Control Plane** (Ryu Controller), and the **Data Plane** (Mininet Emulation).

### 1. The Algorithm (`MCS.py`)
This script implements the core logic described in Section III of the paper.
* **`affected_destinations(G, i, j)`**: Identifies nodes $d$ where all shortest paths traverse the failed link $\langle i, j \rangle$.
* **`candidates(G, nodes, failure_dict)`**: Constructs the boolean Candidate Table $T$, checking if a candidate can tunnel traffic to the destination without using the failed link.
* **`find_minimum_set`**: Iterates through combinations ($N \choose k$) to find the smallest candidate set $C$ that covers all rows in $T$.
* **`best_candidate`**: Implements **MCS-ARPL** (Section IV), selecting the candidate set that minimizes latency.

### 2. The Topology (`abilene_topo.py`)
Defines the Abilene network structure, including bandwidths and latencies, using `NetworkX`. This serves as the source of truth for both the mathematical analysis and the Mininet emulation.

### 3. The Emulation (`run_mn.py` & `traffic_injector.py`)
* **`run_network.py`**: A Mininet script that builds the Abilene topology with Open vSwitch (OVS). It configures QoS queues and connects to a Remote Controller (e.g., Ryu).
* **`innjector.py`**: Parses traffic matrices and generates UDP traffic flows using `iperf` to simulate network load during testing.

### 4. The Controller (`ryu_controller.py`)
This script implements the SDN logic using the **Ryu Framework**. It bridges the MCS algorithm with the OpenFlow switches.
* **Topology Discovery**: Uses LLDP to map the network structure dynamically.
* **Proactive Failover**: Pre-installs "Group Tables" (Fast Failover) on switches based on the MCS calculation.
* **MPLS Tunneling**: Encapsulates redirected traffic with MPLS labels to route it to the designated "Hero" (Candidate) switch during a failure.

---

## 🛠 Prerequisites

To run the full emulation, you need a Linux environment (Ubuntu recommended) with the following installed:

* **Python 3**
* **Mininet** (with Open vSwitch)
* **Ryu Controller** (or any OpenFlow 1.3 controller)
* **NetworkX**

```bash
# Install Python dependencies
pip3 install networkx matplotlib ryu

# Install Mininet (if not already installed)
sudo apt-get install mininet
