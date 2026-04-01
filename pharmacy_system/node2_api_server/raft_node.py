# =============================================================================
#   Q3 — Create node2_api_server/raft_node.py:
#         - States: Follower / Candidate / Leader
#         - Election timeout: random 1.5–3s (reset on heartbeat)
#         - Heartbeat interval: 1s (leader only)
#         - Vote logic: grant if term >= current AND not yet voted this term
#         - Print format: "Node X sends RPC Y to Node Z" / "Node X runs RPC Y called by Node Z"
#
#   Q3 — Wire raft_node.py into server.py; rebuild containers; capture election screenshot.
#
#   Q4 — Extend AppendEntries in raft.proto to carry LogEntry messages.
#         Implement leader log append, majority-ACK commit, DB write.
#         Implement follower-to-leader request forwarding.
# =============================================================================

import os
import sys
import time
import random
import threading
import uuid
import grpc
import psycopg2
from concurrent import futures

sys.path.insert(0, '/app/proto')
import raft_pb2
import raft_pb2_grpc

FOLLOWER = "FOLLOWER"
CANDIDATE = "CANDIDATE"
LEADER = "LEADER"

# NODE_ID is set in docker-compose.yml for each container (1–5)
NODE_ID = int(os.environ.get("NODE_ID", "0"))

# DB connection settings (same as server.py — shared primary DB)
DB_HOST = os.environ.get("DB_HOST", "db-primary")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "pharmacy")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "postgres")

def _get_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )

PARTICIPANTS = [
    (1, "api-server-a"),       
    (2, "api-server-b"),
    (3, "api-server-c"),
    (4, "api-server-d"),
    (5, "api-server-e"),
]
RAFT_PORT = 50054

class raftNode(raft_pb2_grpc.RaftServicer):

    def __init__(self):
        self.state = FOLLOWER
        self.current_term = 0
        self.voted_for = None

        # Q4 Log stuff
        self.log = []         
        self.commit_index = -1  
        self.last_applied = -1   
        self.leader_id = None     

        # Timers
        self.heartbeat_interval = 1.0
        self.reset_election_timeout()
        self.last_heartbeat = time.time()

        self.lock = threading.Lock()
    
    def reset_election_timeout(self):
        self.election_timeout = random.uniform(1.5, 3.0)

    def election_timeout_expired(self):
        if (time.time() - self.last_heartbeat) > self.election_timeout:
            return True
        else:
            return False
        
    # RPC: RequestVote (Candidate → Followers)
    def RequestVote(self, request, context):
        print(f"Node {NODE_ID} runs RPC RequestVote called by Node {request.candidate_id}")

        # return raft_pb2_grpc.VoteResponse(term=self.current_term, vote_recieved=False)
        with self.lock:
            # Check term
            if request.term < self.current_term:    # the requetsed term has passed 
                return raft_pb2.RequestVoteResponse(
                    term = self.current_term, 
                    vote_recieved = False
                    )
            
            if request.term > self.current_term:
                self.current_term = request.term
                self.state = FOLLOWER
                self.voted_for = None

            if self.voted_for is None or self.voted_for == request.candidate_id:
                self.voted_for = request.candidate_id
                return raft_pb2.RequestVoteResponse(
                    term = self.current_term, 
                    vote_recieved = True
                    )

            return raft_pb2.RequestVoteResponse(
                term = self.current_term, 
                vote_recieved = False
                )


    # RPC: AppendEntries (Leader → Followers) [Heartbeat]
    def AppendEntries(self, request, context):
        print(f"Node {NODE_ID} runs RPC AppendEntries called by Node {request.leader_id}")

        with self.lock:
            if request.term < self.current_term:
                return raft_pb2.AppendEntriesResponse(
                    term = self.current_term, 
                    success = False
                    )

            # Accept leader heartbeat
            self.current_term = request.term
            self.state = FOLLOWER
            self.leader_id = request.leader_id
            self.last_heartbeat = time.time()
            self.reset_election_timeout()
            self.voted_for = None

            self.log = list(request.log)

            while self.last_applied < request.commit_index:
                self.last_applied += 1
                entry = self.log[self.last_applied]
                print(f"[APPLY] Node {NODE_ID} executes: {entry.command}")

            self.commit_index = request.commit_index

            return raft_pb2.AppendEntriesResponse(
                term = self.current_term, 
                success=True
                )
        

    # STATE: Candidate 
    def start_election(self):
        with self.lock:
            self.state = CANDIDATE
            self.current_term += 1
            self.voted_for = NODE_ID
            votes = 1 
            #fails = 0
            self.last_heartbeat = time.time()
            self.reset_election_timeout()

        for participant_id, host in PARTICIPANTS:
            if participant_id == NODE_ID:
                continue
            addr = f"{host}:{RAFT_PORT}"
            try:
                channel = grpc.insecure_channel(addr)
                stub = raft_pb2_grpc.RaftStub(channel)
                print(f"Node {NODE_ID} sends RPC RequestVote to Node {participant_id}")

                response_msg = stub.RequestVote(
                    raft_pb2.RequestVoteRequest(
                        term = self.current_term, 
                        candidate_id = NODE_ID
                    )
                )

                if response_msg.vote_recieved:
                    votes += 1
                
                if response_msg.term > self.current_term:
                    with self.lock:
                        self.current_term = response_msg.term
                        self.state = FOLLOWER

            except Exception:# as e:  
                #continue
                #fails += 1
                print(f"[Raft] Start election delivery to Node {participant_id} failed")#: {e}")
        
        # check results
        if votes > len(PARTICIPANTS) // 2:
            print(f"[RAFT] Node {NODE_ID} becomes LEADER")
            self.state = LEADER
        else:
            self.state = FOLLOWER
            if votes == 1:
                print(f"[RAFT] Node {NODE_ID} is isolated → backing off")
                time.sleep(random.uniform(1.5, 3.0))
                return
            #time.sleep(random.uniform(0.5, 1.5))
    
    def send_heartbeats(self):
        success_count = 1
        for participant_id, host in PARTICIPANTS:
            if participant_id == NODE_ID:
                continue
            addr = f"{host}:{RAFT_PORT}"
            try:
                channel = grpc.insecure_channel(addr)
                stub = raft_pb2_grpc.RaftStub(channel)
                print(f"Node {NODE_ID} sends RPC AppendEntries to Node {participant_id}")

                response_msg = stub.AppendEntries(
                    raft_pb2.AppendEntriesRequest(
                        term = self.current_term,
                        leader_id = NODE_ID,
                        log=self.log, 
                        commit_index=self.commit_index 
                    ),
                    timeout=0.3
                )
                if response_msg.success:
                    success_count += 1

                # If candidate/leader discovers that its term is stale, revert to follower
                if response_msg.term > self.current_term:
                    with self.lock:
                        self.current_term = response_msg.term
                        self.state = FOLLOWER

            except Exception: # as e:  
                #continue
                print(f"[Raft] Heartbeat delivery to Node {participant_id} failed")#: {e}")

        if success_count <= len(PARTICIPANTS) // 2:
            print(f"[RAFT] Node {NODE_ID} lost majority → stepping down")
            self.state = FOLLOWER
    
    def ClientCommand(self, request, context):
        print(f"Node {NODE_ID} received client command: {request.command}")

        # If not leader → forward
        if self.state != LEADER:
            if self.leader_id is None:
                return raft_pb2.ClientResponse(
                    success = False, 
                    message = "No leader"
                    )
            
            for participant_id, host in PARTICIPANTS:
                if participant_id == self.leader_id:
                    addr = f"{host}:{RAFT_PORT}"
                    print(f"Node {NODE_ID} forwards request to Node {participant_id}")
                    try:
                        channel = grpc.insecure_channel(addr)
                        stub = raft_pb2_grpc.RaftStub(channel)
                        return stub.ClientCommand(
                            request, 
                            timeout=0.3)
                    except:
                        return raft_pb2.ClientResponse(
                            success = False, 
                            message = "Leader unreachable")
                    
        with self.lock:
            new_index = len(self.log)
            entry = raft_pb2.LogEntry(
                term=self.current_term,
                index=new_index,
                command=request.command
            )
            self.log.append(entry)

        print(f"[LOG] Node {NODE_ID} appended: {request.command}")

        success_count = 1
        for participant_id, host in PARTICIPANTS:
            if participant_id == NODE_ID:
                continue
            addr = f"{host}:{RAFT_PORT}"
            try:
                channel = grpc.insecure_channel(addr)
                stub = raft_pb2_grpc.RaftStub(channel)
                print(f"Node {NODE_ID} sends RPC AppendEntries to Node {participant_id}")

                response_msg = stub.AppendEntries(
                    raft_pb2.AppendEntriesRequest(
                        term = self.current_term,
                        leader_id = NODE_ID,
                        log=self.log, 
                        commit_index=self.commit_index 
                    ),
                    timeout=0.3
                )
                if response_msg.success:
                    success_count += 1

            except Exception: # as e:  
                continue
                # print(f"[Raft] Heartbeat delivery to Node {participant_id} failed")#: {e}")

        if success_count > len(PARTICIPANTS) // 2:
            self.commit_index += 1

            entry = self.log[self.commit_index]
            print(f"[COMMIT] Node {NODE_ID} commits: {entry.command}")

            return raft_pb2.ClientResponse(
            success = True,
            message = f"Committed: {entry.command}"
        )

        return raft_pb2.ClientResponse(
            success = False,
            message = "Failed to reach majority"
        )
    
    def apply_entry_to_db(self, command):
        try:
            parts = command.split(":")
            if parts[0] == "UPDATE":
                drug_id = int(parts[1])
                new_qty = int(parts[2])

                conn = _get_connection()
                cur = conn.cursor()

                cur.execute(
                    "UPDATE drugs SET quantity = %s WHERE id = %s",
                    (new_qty, drug_id)
                )

                conn.commit()
                cur.close()
                conn.close()

                

                print(f"[DB] Node {NODE_ID} updated drug {drug_id} → {new_qty}")

        except Exception as e:
            print(f"[DB ERROR] Node {NODE_ID}: {e}")

    def run(self):
        while True:
            time.sleep(0.1)

            if self.state == FOLLOWER:
                if self.election_timeout_expired():
                    print(f"[RAFT] Node {NODE_ID} timeout → CANDIDATE")
                    self.start_election()

            elif self.state == CANDIDATE:
                if self.election_timeout_expired():
                    self.start_election()

            elif self.state == LEADER:
                self.send_heartbeats()
                time.sleep(self.heartbeat_interval)


def serve_raft(node):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    raft_pb2_grpc.add_RaftServicer_to_server(node, server)
    server.add_insecure_port('[::]:50054')
    server.start()
    return server
