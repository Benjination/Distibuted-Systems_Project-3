# =============================================================================
# [PROJECT 3] coordinator.py — Two-Phase Commit Coordinator (Q1 + Q2)
#
# This module implements the COORDINATOR side of the 2PC protocol.
# It runs as a gRPC service on port 50053, but ONLY on Node 1 (api-server-a).
# Nodes 2–5 do not start this service.
#
# When a client calls UpdateStock2PC, the coordinator drives the full protocol:
#
#   Q1 — Vote Phase:
#     1. Generates a unique transaction ID
#     2. Sends VoteRequest to ALL 5 participant nodes (including itself on
#        localhost:50052) via gRPC
#     3. Collects votes — VoteCommit or VoteAbort from each participant
#
#   Q2 — Decision Phase:
#     4. If all 5 voted COMMIT → sends GlobalCommit to all 5 participants
#        If any voted ABORT  → sends GlobalAbort to all 5 participants
#     5. Returns result to the original client
#
# Intra-node gRPC: the coordinator calls its own participant service on
# localhost:50052, satisfying the requirement that voting and decision phases
# communicate over gRPC even within the same container.
#
# Print statement format (required by assignment):
#   "Phase decision of Node X sends RPC <rpc> to Phase voting of Node Y"
# =============================================================================

import os
import sys
import uuid
import grpc
from concurrent import futures

sys.path.insert(0, '/app/proto')
import pharmacy_pb2
import pharmacy_pb2_grpc

# NODE_ID of this coordinator (always 1 — api-server-a)
NODE_ID = int(os.environ.get("NODE_ID", "1"))

# Addresses of all 5 participant services (port 50052).
# The coordinator uses "localhost" for its own node so the call goes through
# gRPC on the loopback interface — demonstrating intra-node gRPC communication.
PARTICIPANTS = [
    (1, "localhost"),       # self — demonstrates same-node gRPC (voting ↔ decision)
    (2, "api-server-b"),
    (3, "api-server-c"),
    (4, "api-server-d"),
    (5, "api-server-e"),
]
PARTICIPANT_PORT = 50052


class CoordinatorServicer(pharmacy_pb2_grpc.CoordinatorServiceServicer):
    """
    [PROJECT 3] Coordinator node for two-phase commit.
    Exposes UpdateStock2PC to clients and orchestrates the full 2PC protocol.
    """

    def UpdateStock2PC(self, request, context):
        """
        Entry point for a 2PC-protected stock update.
        Runs the full vote → decision cycle across all 5 participant nodes.
        """
        transaction_id = str(uuid.uuid4())[:8].upper()
        drug_id        = request.id
        new_quantity   = request.quantity

        print(f"\n{'='*60}")
        print(f"[2PC] Coordinator Node {NODE_ID} — Transaction {transaction_id}")
        print(f"[2PC] Operation: UpdateStock  drug_id={drug_id}  new_qty={new_quantity}")
        print(f"{'='*60}")

        # =====================================================================
        # Q1 — VOTE PHASE: send VoteRequest to all participants
        # =====================================================================
        votes = []  # list of (node_id, vote_commit: bool, reason: str)

        for participant_id, host in PARTICIPANTS:
            addr = f"{host}:{PARTICIPANT_PORT}"
            try:
                channel = grpc.insecure_channel(addr)
                stub    = pharmacy_pb2_grpc.TwoPhaseParticipantServiceStub(channel)

                vote_req = pharmacy_pb2.VoteRequestMsg(
                    transaction_id = transaction_id,
                    drug_id        = drug_id,
                    new_quantity   = new_quantity,
                    coordinator_id = NODE_ID
                )

                # Required client-side print for vote phase (Q1)
                print(f"Phase decision of Node {NODE_ID} sends RPC VoteRequest "
                      f"to Phase voting of Node {participant_id}")

                resp = stub.VoteRequest(vote_req, timeout=5.0)
                votes.append((participant_id, resp.vote_commit, resp.reason))

                vote_word = "COMMIT" if resp.vote_commit else "ABORT"
                print(f"[2PC] Node {participant_id} voted {vote_word}: {resp.reason}")

            except Exception as e:
                # Unreachable node is treated as an ABORT vote
                print(f"[2PC] Node {participant_id} unreachable ({addr}): {e} → ABORT")
                votes.append((participant_id, False, f"unreachable: {e}"))

        all_commit = all(v[1] for v in votes)
        print(f"\n[2PC] Vote phase complete — decision: {'COMMIT' if all_commit else 'ABORT'}")

        # =====================================================================
        # Q2 — DECISION PHASE: broadcast GlobalCommit or GlobalAbort
        # =====================================================================
        acks = []

        for participant_id, host in PARTICIPANTS:
            addr = f"{host}:{PARTICIPANT_PORT}"
            try:
                channel = grpc.insecure_channel(addr)
                stub    = pharmacy_pb2_grpc.TwoPhaseParticipantServiceStub(channel)

                decision_msg = pharmacy_pb2.GlobalDecisionMsg(
                    transaction_id = transaction_id,
                    coordinator_id = NODE_ID,
                    drug_id        = drug_id,
                    new_quantity   = new_quantity
                )

                if all_commit:
                    # Required client-side print for decision phase (Q2)
                    print(f"Phase decision of Node {NODE_ID} sends RPC GlobalCommit "
                          f"to Phase voting of Node {participant_id}")
                    ack = stub.GlobalCommit(decision_msg, timeout=5.0)
                else:
                    print(f"Phase decision of Node {NODE_ID} sends RPC GlobalAbort "
                          f"to Phase voting of Node {participant_id}")
                    ack = stub.GlobalAbort(decision_msg, timeout=5.0)

                acks.append(ack)

            except Exception as e:
                print(f"[2PC] Decision delivery to Node {participant_id} failed: {e}")

        print(f"[2PC] Decision phase complete — {len(acks)}/5 ACKs received")
        print(f"{'='*60}\n")

        # Return result to the client
        if all_commit:
            return pharmacy_pb2.DrugResponse(
                success = True,
                message = (f"[2PC] Transaction {transaction_id} COMMITTED on all nodes. "
                           f"drug_id={drug_id} quantity updated to {new_quantity}")
            )
        else:
            abort_reasons = [
                f"Node {nid}: {reason}"
                for nid, committed, reason in votes
                if not committed
            ]
            return pharmacy_pb2.DrugResponse(
                success = False,
                message = (f"[2PC] Transaction {transaction_id} ABORTED. "
                           f"Reasons: {'; '.join(abort_reasons)}")
            )


def serve_coordinator():
    """
    Start the CoordinatorService gRPC server on port 50053.
    Called from server.py only when NODE_ID == 1.
    Returns the running server object (non-blocking).
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pharmacy_pb2_grpc.add_CoordinatorServiceServicer_to_server(
        CoordinatorServicer(), server
    )
    server.add_insecure_port('[::]:50053')
    server.start()
    print(f"[PROJECT 3] CoordinatorService started on port 50053 (Node {NODE_ID})")
    return server
