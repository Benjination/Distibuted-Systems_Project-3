# Distributed Pharmacy System — Project 3

**CSE-5306 Distributed Systems**

**Team Members:**
- Madison Gage (Student ID: 1001770778)
- Benjamin Niccum (Student ID: 1002111609)

**GitHub Repository:** https://github.com/Benjination/Distibuted-Systems-Project-3

---

## Overview

This project extends a distributed pharmacy inventory system with:
- **Two-Phase Commit (2PC)** for atomic distributed transactions across 5 nodes
- **Raft Consensus** for leader election and log replication

**Architecture:** 5 gRPC API servers with NGINX load balancer, PostgreSQL replication, running in Docker containers.

**Port Assignment:**
- `50051` — PharmacyService (original gRPC service)
- `50052` — TwoPhaseParticipantService (2PC, all nodes)
- `50053` — CoordinatorService (2PC coordinator, Node 1 only)
- `50054` — RaftService (Raft consensus, all nodes)

---

## How to Compile and Run

### Prerequisites
- Docker Desktop (running)
- Python 3.10+

### 1. Setup

```bash
git clone https://github.com/Benjination/Distibuted-Systems-Project-3.git
cd pharmacy_system
pip install -r requirements.txt
```

### 2. Start Services

Proto compilation happens automatically inside Docker containers at build time.

```bash
docker-compose up --build -d
```

Wait ~15 seconds for initialization. Verify with `docker ps` (should see 11 containers running).

### 3. Test Two-Phase Commit

```bash
python client/twopc_client.py
```

### 4. Observe Raft Leader Election

```bash
docker logs node2-api-server-a | grep RAFT
```

Expected output:
```
[RAFT] Node 1 timeout → CANDIDATE
[RAFT] Node 1 becomes LEADER
Node 1 sends RPC AppendEntries to Node 2
...
```

### 5. Run Raft Failure Tests

Filter logs to see elections without heartbeat spam:
```bash
docker compose logs -f api-server-a api-server-b api-server-c api-server-d api-server-e \
  | grep -E "RAFT|CANDIDATE|LEADER|RequestVote"
```

Then in another terminal, run failure scenarios:
```bash
# Test 1: Stop follower
docker compose stop api-server-b

# Test 2: Rejoin follower  
docker compose start api-server-b

# Test 3: Stop leader (identify from logs first)
docker compose stop api-server-a

# Test 4: Rejoin old leader
docker compose start api-server-a

# Test 5: Quorum rule (2 failures OK, 3 failures lose quorum)
docker compose stop api-server-d api-server-e  # Still works
docker compose stop api-server-c               # Quorum lost
docker compose start api-server-c api-server-d api-server-e  # Recover
```

### 6. Shutdown

```bash
docker-compose down -v
```

---

## Anything Unusual

- **Proto Compilation:** Proto files compile automatically inside Docker containers at build time. No need to run `generate_proto.sh` manually on the host.
- **Raft Election Timing:** Leader election uses randomized timeouts (1.5-3.0s). May take 3-5 seconds on first boot before a leader is elected.
- **2PC Coordinator:** Only Node 1 (api-server-a) runs the CoordinatorService on port 50053. All other nodes are participants only.
- **Log Filtering:** Use the grep filter shown above to observe Raft elections without heartbeat spam.

---

## External Sources Referenced

1. **Raft Consensus Algorithm**
   - "In Search of an Understandable Consensus Algorithm" by Ongaro & Ousterhout (2014)
   - https://raft.github.io/raft.pdf

2. **Two-Phase Commit Protocol**
   - Distributed Systems: Principles and Paradigms by Tanenbaum & Van Steen
   - CSE 5306 course lecture materials

3. **gRPC and Protocol Buffers**
   - https://grpc.io/docs/languages/python/
   - https://protobuf.dev/

4. **AI Assistance**
   - GitHub Copilot (Claude Sonnet 4.6) for proto scaffolding, boilerplate generation, Raft implementation strategy, troubleshooting, and report formatting
