# =============================================================================
# [PROJECT 3] twopc_client.py — Two-Phase Commit Test Client
#
# Connects to the CoordinatorService on Node 1 (api-server-a, port 50053)
# and calls UpdateStock2PC to trigger the full 2PC protocol across all 5 nodes.
#
# Usage (from pharmacy_system/ with .venv active):
#   python client/twopc_client.py
#   python client/twopc_client.py localhost 50053   # explicit host/port
#
# What to observe in terminal output:
#   - Coordinator print: "Phase decision of Node 1 sends RPC VoteRequest to Phase voting of Node X"
#   - Participant print: "Phase voting of Node X sends RPC VoteCommit/VoteAbort to Phase decision of Node 1"
#   - Coordinator print: "Phase decision of Node 1 sends RPC GlobalCommit/GlobalAbort to Phase voting of Node X"
#   - Participant print: "Phase voting of Node X sends RPC GlobalCommitAck to Phase decision of Node 1"
#
# View live output from all nodes with:
#   docker logs -f node2-api-server-a
#   docker logs -f node3-api-server-b   (etc.)
# =============================================================================

import grpc
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../proto'))
import pharmacy_pb2
import pharmacy_pb2_grpc


def run(host="localhost", port="50053"):
    channel = grpc.insecure_channel(f"{host}:{port}")
    stub    = pharmacy_pb2_grpc.CoordinatorServiceStub(channel)

    print("=" * 60)
    print(" [PROJECT 3] Two-Phase Commit Test Client")
    print(f" Coordinator: {host}:{port}  (Node 1 / api-server-a)")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Test 1: Happy path — update stock on an existing drug
    # Expected: all 5 nodes vote COMMIT → GlobalCommit sent → DB updated
    # ------------------------------------------------------------------
    print("\n[Test 1] 2PC UpdateStock — drug_id=1, new_quantity=250 (happy path)")
    print("         All participants should vote COMMIT.\n")

    resp = stub.UpdateStock2PC(
        pharmacy_pb2.UpdateStockRequest(id=1, quantity=250),
        timeout=30.0
    )
    print(f"\nClient received: success={resp.success}")
    print(f"Message: {resp.message}")

    # ------------------------------------------------------------------
    # Test 2: Abort path — try to update a drug that does not exist
    # Expected: all 5 nodes vote ABORT (drug not found) → GlobalAbort sent
    # ------------------------------------------------------------------
    print("\n" + "-" * 60)
    print("[Test 2] 2PC UpdateStock — drug_id=9999, new_quantity=1 (abort path)")
    print("         All participants should vote ABORT (drug not found).\n")

    resp = stub.UpdateStock2PC(
        pharmacy_pb2.UpdateStockRequest(id=9999, quantity=1),
        timeout=30.0
    )
    print(f"\nClient received: success={resp.success}")
    print(f"Message: {resp.message}")

    print("\n" + "=" * 60)
    print(" 2PC test complete.")
    print(" Check each container's logs for the full protocol output:")
    print("   docker logs node2-api-server-a")
    print("   docker logs node3-api-server-b")
    print("   docker logs node7-api-server-c")
    print("   docker logs node8-api-server-d")
    print("   docker logs node9-api-server-e")
    print("=" * 60)


if __name__ == "__main__":
    h = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    p = sys.argv[2] if len(sys.argv) > 2 else "50053"
    run(h, p)
