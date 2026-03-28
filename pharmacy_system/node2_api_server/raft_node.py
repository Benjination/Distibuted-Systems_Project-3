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
from concurrent import futures

sys.path.insert(0, '/app/proto')
import raft_pb2
import raft_pb2_grpc

FOLLOWER = "FOLLOWER"
CANDIDATE = "CANDIDATE"
LEADER = "LEADER"

# NODE_ID is set in docker-compose.yml for each container (1–5)
NODE_ID = int(os.environ.get("NODE_ID", "0"))

PARTICIPANTS = [
    (1, "api-server-a"),       
    (2, "api-server-b"),
    (3, "api-server-c"),
    (4, "api-server-d"),
    (5, "api-server-e"),
]
PARTICIPANT_PORT = 50051

class raftNode(raft_pb2_grpc.RaftServiceServicer):

    def __init__(self):
        self.state = FOLLOWER
        self.current_term = 0
        self.voted_for = None

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
                return raft_pb2_grpc.VoteResponse(
                    term = self.current_term, 
                    vote_recieved = False
                    )
            
            if request.term > self.current_term:
                self.current_term = request.term
                self.state = FOLLOWER
                self.voted_for = None

            if self.voted_for is None or self.voted_for == request.candidate_id:
                self.voted_for = request.candidate_id
                return raft_pb2.VoteResponse(
                    term = self.current_term, 
                    vote_granted = True
                    )

            return raft_pb2.VoteResponse(
                term = self.current_term, 
                vote_granted = False
                )


    # RPC: AppendEntries (Leader → Followers) [Heartbeat]
    def AppendEntries(self, request, context):
        print(f"Node {NODE_ID} runs RPC AppendEntries called by Node {request.leader_id}")

        with self.lock:
            if request.term < self.current_term:
                return raft_pb2.AppendResponse(
                    term = self.current_term, 
                    success = False
                    )

            # Accept leader heartbeat
            self.current_term = request.term
            self.state = FOLLOWER
            self.last_heartbeat = time.time()
            self.voted_for = None

            return raft_pb2.AppendResponse(
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

        for participant_id, host in PARTICIPANTS:
            if participant_id != NODE_ID:
                addr = f"{host}:{PARTICIPANT_PORT}"
            try :
                channel = grpc.insecure_channel(addr)
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                print(f"Node {NODE_ID} sends RPC RequestVote to Node {participant_id}")

                response_msg = stub.RequestVote(
                    raft_pb2.VoteRequest(
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

            except Exception as e:  
                print(f"[Raft] Start election delivery to Node {participant_id} failed: {e}")
        
        # check results
        if votes > (len(PARTICIPANTS) + 1) // 2:
            print(f"[RAFT] Node {NODE_ID} becomes LEADER")
            self.state = LEADER
        else:
            self.state = FOLLOWER
    
    def send_heartbeats(self):
        for participant_id, host in PARTICIPANTS:
            if participant_id != NODE_ID:
                addr = f"{host}:{PARTICIPANT_PORT}"
            try:
                channel = grpc.insecure_channel(addr)
                stub = raft_pb2_grpc.RaftServiceStub(channel)
                print(f"Node {NODE_ID} sends RPC AppendEntries to Node {participant_id}")

                response_msg = stub.AppendEntries(
                    raft_pb2.AppendRequest(
                        term = self.current_term,
                        leader_id = NODE_ID
                    )
                )

                # If candidate/leader discovers that its term is stale, revert to follower
                if response_msg.term > self.current_term:
                    with self.lock:
                        self.current_term = response_msg.term
                        self.state = FOLLOWER

            except Exception as e:  
                print(f"[Raft] Heartbeat delivery to Node {participant_id} failed: {e}")


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

    def serve_raft():
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        raft_pb2_grpc.add_RaftServiceServicer_to_server(RaftNodeServicer(), server)
    