# =============================================================================
# [PROJECT 3] participant.py — Two-Phase Commit Participant (Q1 + Q2)
#
# This module implements the PARTICIPANT side of the 2PC protocol.
# It runs as a gRPC service on port 50052 on ALL 5 API server containers.
#
# Q1 — Vote Phase:
#   VoteRequest RPC: coordinator asks "can you commit this stock update?"
#     - Checks the drug exists in the DB
#     - Stores the pending transaction in memory
#     - Replies VoteCommit if drug found, VoteAbort otherwise
#
# Q2 — Decision Phase:
#   GlobalCommit RPC: coordinator says "everyone voted yes — commit locally"
#     - Node 1 (coordinator node) applies the actual DB UPDATE
#     - Other nodes log the commit (shared DB means only one node writes)
#   GlobalAbort RPC: coordinator says "someone voted no — abort locally"
#     - All nodes discard the pending transaction
#
# Print statement format (required by assignment):
#   Client side (coordinator): "Phase decision of Node X sends RPC <rpc> to Phase voting of Node Y"
#   Server side (participant):  "Phase voting of Node Y sends RPC <rpc> to Phase decision of Node X"
# =============================================================================

import os
import sys
import threading
import psycopg2

sys.path.insert(0, '/app/proto')
import pharmacy_pb2
import pharmacy_pb2_grpc

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

# In-memory store for pending (uncommitted) transactions.
# Key: transaction_id, Value: (drug_id, new_quantity)
# Protected by a lock for thread safety.
_pending_transactions: dict = {}
_pending_lock = threading.Lock()


class TwoPhaseParticipantServicer(pharmacy_pb2_grpc.TwoPhaseParticipantServiceServicer):
    """
    [PROJECT 3] Participant node for two-phase commit.
    Handles VoteRequest (Q1) and GlobalCommit/GlobalAbort (Q2).
    """

    # -------------------------------------------------------------------------
    # Q1 — Vote Phase
    # -------------------------------------------------------------------------
    def VoteRequest(self, request, context):
        """
        Coordinator calls this on every participant to ask for a vote.
        We check whether the drug exists; if yes we vote COMMIT, else ABORT.
        The pending transaction is stored in memory until the global decision
        arrives in GlobalCommit or GlobalAbort below.
        """
        # Server-side required print (participant "sends" its vote back)
        print(f"Phase voting of Node {NODE_ID} receives RPC VoteRequest "
              f"from Phase decision of Node {request.coordinator_id}")

        try:
            conn = _get_connection()
            cur  = conn.cursor()
            cur.execute("SELECT id FROM drugs WHERE id = %s", (request.drug_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()

            if not row:
                # Drug does not exist — vote ABORT
                print(f"Phase voting of Node {NODE_ID} sends RPC VoteAbort "
                      f"to Phase decision of Node {request.coordinator_id}")
                return pharmacy_pb2.VoteResponseMsg(
                    transaction_id = request.transaction_id,
                    participant_id = NODE_ID,
                    vote_commit    = False,
                    reason         = f"Drug {request.drug_id} not found"
                )

            # Drug exists — record pending transaction and vote COMMIT
            with _pending_lock:
                _pending_transactions[request.transaction_id] = (
                    request.drug_id, request.new_quantity
                )

            print(f"Phase voting of Node {NODE_ID} sends RPC VoteCommit "
                  f"to Phase decision of Node {request.coordinator_id}")
            return pharmacy_pb2.VoteResponseMsg(
                transaction_id = request.transaction_id,
                participant_id = NODE_ID,
                vote_commit    = True,
                reason         = "Drug found, ready to commit"
            )

        except Exception as e:
            # Any DB error → ABORT
            print(f"Phase voting of Node {NODE_ID} sends RPC VoteAbort "
                  f"to Phase decision of Node {request.coordinator_id} (error: {e})")
            return pharmacy_pb2.VoteResponseMsg(
                transaction_id = request.transaction_id,
                participant_id = NODE_ID,
                vote_commit    = False,
                reason         = str(e)
            )

    # -------------------------------------------------------------------------
    # Q2 — Decision Phase: GlobalCommit
    # -------------------------------------------------------------------------
    def GlobalCommit(self, request, context):
        """
        Coordinator calls this after ALL participants voted COMMIT.
        Node 1 (which is also the coordinator node) applies the actual DB UPDATE.
        All other nodes log the commit — they share the same PostgreSQL primary DB,
        so having 5 nodes all write the same row would cause duplicate updates.
        This design reflects a realistic shared-storage 2PC deployment.
        """
        print(f"Phase voting of Node {NODE_ID} receives RPC GlobalCommit "
              f"from Phase decision of Node {request.coordinator_id}")

        with _pending_lock:
            _pending_transactions.pop(request.transaction_id, None)

        # Only the coordinator node writes to the DB to prevent duplicate updates
        # on the shared PostgreSQL instance.
        if NODE_ID == request.coordinator_id:
            try:
                conn = _get_connection()
                cur  = conn.cursor()
                cur.execute(
                    "UPDATE drugs SET quantity = %s WHERE id = %s",
                    (request.new_quantity, request.drug_id)
                )
                conn.commit()
                cur.close()
                conn.close()
                msg = f"Node {NODE_ID} applied DB UPDATE: drug {request.drug_id} qty → {request.new_quantity}"
                print(f"[2PC] {msg}")
            except Exception as e:
                msg = f"Node {NODE_ID} DB write failed: {e}"
                print(f"[2PC] ERROR: {msg}")
        else:
            msg = f"Node {NODE_ID} locally committed (DB write handled by coordinator node)"
            print(f"[2PC] {msg}")

        print(f"Phase voting of Node {NODE_ID} sends RPC GlobalCommitAck "
              f"to Phase decision of Node {request.coordinator_id}")
        return pharmacy_pb2.GlobalDecisionAck(
            transaction_id = request.transaction_id,
            participant_id = NODE_ID,
            success        = True,
            message        = msg
        )

    # -------------------------------------------------------------------------
    # Q2 — Decision Phase: GlobalAbort
    # -------------------------------------------------------------------------
    def GlobalAbort(self, request, context):
        """
        Coordinator calls this if ANY participant voted ABORT.
        All participants discard their pending transaction — no DB write occurs.
        """
        print(f"Phase voting of Node {NODE_ID} receives RPC GlobalAbort "
              f"from Phase decision of Node {request.coordinator_id}")

        with _pending_lock:
            _pending_transactions.pop(request.transaction_id, None)

        msg = f"Node {NODE_ID} locally aborted transaction {request.transaction_id}"
        print(f"[2PC] {msg}")

        print(f"Phase voting of Node {NODE_ID} sends RPC GlobalAbortAck "
              f"to Phase decision of Node {request.coordinator_id}")
        return pharmacy_pb2.GlobalDecisionAck(
            transaction_id = request.transaction_id,
            participant_id = NODE_ID,
            success        = True,
            message        = msg
        )
