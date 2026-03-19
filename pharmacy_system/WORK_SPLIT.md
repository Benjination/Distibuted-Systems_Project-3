# Project 3 — Work Division

Q1 and Q2 (Two-Phase Commit) are already fully implemented and tested.
The remaining work is Q3 (Raft leader election), Q4 (Raft log replication),
and Q5 (failure tests + report).

We split the work so that both partners can make meaningful progress
simultaneously, with only one sync point needed before the final submission.

---

## Role A — Raft Implementation (Q3 + Q4)

**Files owned:**
- `proto/raft.proto`
- `node2_api_server/raft_node.py` (new file)
- `node2_api_server/server.py` (Raft wiring only — add the startup call)

### Q3 — Leader Election

1. Define `raft.proto` with two services:
   - `RequestVote(RequestVoteMsg) returns (RequestVoteReply)`
   - `AppendEntries(AppendEntriesMsg) returns (AppendEntriesReply)`

2. Create `raft_node.py` implementing the Raft state machine:
   - Three states: **Follower**, **Candidate**, **Leader**
   - Election timeout: random between 1.5s and 3s (reset on any heartbeat received)
   - Heartbeat interval: 1s (sent by the leader to all other nodes)
   - On timeout: Follower becomes Candidate, increments term, sends `RequestVote` to all peers
   - Vote granted if: requester's term ≥ current term AND node hasn't voted this term
   - Candidate becomes Leader on majority votes (≥ 3 of 5)
   - Leader sends `AppendEntries` (empty, as heartbeat) every 1s to reset follower timers

3. Required print format:
   - Sender side: `Node <id> sends RPC <rpc_name> to Node <id>`
   - Receiver side: `Node <id> runs RPC <rpc_name> called by Node <id>`

4. Wire into `server.py`:
   - Import `RaftNode` from `raft_node.py`
   - Start the Raft thread after the existing gRPC servers start
   - Tag all additions with `# [PROJECT 3]`

5. Rebuild containers and verify election happens:
   ```
   docker compose up --build -d
   sleep 5
   docker logs node2-api-server-a | grep -E "Node|Raft"
   ```

### Q4 — Log Replication

Extend `raft_node.py` (no new files needed):

1. Add log entry structure to `raft.proto`:
   - `AppendEntriesMsg` gains a `repeated LogEntry entries` field
   - `LogEntry` carries: `term`, `operation` (add/update/delete), `drug_id`, `payload`

2. Leader behavior when a client sends a drug operation:
   - Append the entry to its own log
   - Send `AppendEntries` with the new entry to all followers
   - Wait for ACKs from ≥ 3 nodes (majority)
   - On majority: mark entry committed, execute the DB write

3. Non-leader behavior:
   - If a client connects to a follower or candidate, forward the request
     to the known leader (or reply with the leader's address so the client retries)

4. Verify with `raft_test_client.py` (written by Role B — it will be ready when you are).

---

## Role B — Testing, Client Code & Report (Q4 support + Q5)

Everything in this role can be written and completed **without waiting** on
Role A, because it is either client-side code, test scripts, or documentation.
When Role A signals that Raft is running, Role B plugs in the captured output
and the work is done.

**Files owned:**
- `client/raft_test_client.py` (new file)
- `client/q5_failure_tests.py` (new file)
- `README.md`
- Final report document

### Write `raft_test_client.py` (do this now)

This client will be used to test Q3 and Q4 once Role A's Raft is running.
Write it now — it is pure client code and does not require a Raft server.

```
Connect to any node (e.g. localhost:50051 via NGINX load balancer)
Send a drug operation (AddDrug, UpdateStock, DeleteDrug)
Print which node handled it and whether it was forwarded to a leader
```

Structure it so it can be pointed at any of the 5 nodes to test forwarding.

### Write `q5_failure_tests.py` (do this now)

Script all 5 failure scenarios. Each test should:
1. Print what it is about to do
2. Execute the failure (e.g. `docker stop node3-api-server-b`)
3. Wait a few seconds
4. Run an operation and observe the result
5. Restore the node (`docker start node3-api-server-b`)

Suggested 5 scenarios:
1. **Leader crash** — stop whichever node is currently leader; observe re-election
2. **Follower crash** — stop one follower; confirm operations still commit (4/5 majority)
3. **Two followers crash** — stop two followers; system still has majority (3/5), should still work
4. **Minority partition** — stop three nodes; majority lost, system should stall (no commits)
5. **2PC with participant down** — stop one API server during a 2PC transaction; all nodes vote ABORT

These can be written as Python scripts using `subprocess` to call `docker stop/start`,
without Raft needing to be running yet.

### Update `README.md` (do this now)

Document the full project:
- Architecture overview (5 API nodes, NGINX, PostgreSQL primary/replica)
- Port map (8080 NGINX, 50051 PharmacyService, 50052 Participant, 50053 Coordinator)
- How to start the stack: `docker compose up --build -d`
- How to run each test client
- 2PC design summary (coordinator on Node 1, participants on all 5)
- Raft design summary (from `raft.proto` and the proto comments — no running code needed)

### Write the report (start now, finish after sync)

- **Q1 + Q2 sections**: fully writable now. All output is captured.
  Use the print statements from `docker logs node2-api-server-a` as evidence.
- **Q3 + Q4 sections**: write the design and architecture explanation now.
  Leave `[screenshot]` and `[log output]` placeholders.
- **Q5 section**: write the test case designs now (what you're breaking, what you expect).
  Leave `[result]` placeholders.

---

## Sync Point

The one moment coordination is needed:

> **Role A says: "Raft is up and elections are printing correctly."**

At that point:
- Role B runs `raft_test_client.py` — already written, takes minutes
- Role B runs `q5_failure_tests.py`, takes screenshots, pastes output into report
- Role B fills in the `[screenshot]` and `[log output]` placeholders

Everything else is already done.

---

## Summary

| Task | Role | Depends on |
|---|---|---|
| `raft.proto` | A | nothing |
| `raft_node.py` — election | A | `raft.proto` |
| `raft_node.py` — log replication | A | election working |
| `server.py` — Raft wiring | A | `raft_node.py` |
| `raft_test_client.py` | B | nothing (write now) |
| `q5_failure_tests.py` | B | nothing (write now) |
| `README.md` | B | nothing (write now) |
| Report Q1/Q2 sections | B | nothing (write now) |
| Report Q3/Q4 design sections | B | nothing (write now, add output at sync) |
| Report Q5 results + screenshots | B | Raft running (sync point) |
