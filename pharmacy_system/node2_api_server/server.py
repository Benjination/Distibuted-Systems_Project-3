# =============================================================================
# ORIGINAL PROJECT (pharmacy_system, Project 2)
# -----------------------------------------------
# This file was written by the original group to implement a distributed
# pharmacy inventory system using gRPC. It defines PharmacyServicer which
# handles: AddDrug, GetDrug, UpdateStock, DeleteDrug, ListDrugs, GetLowStock.
# All RPCs write directly to a PostgreSQL primary database.
#
# PROJECT 3 ADDITIONS (our work) are marked with "# [PROJECT 3]" comments.
# We extend this server with:
#   - 2PC participant logic (vote phase + decision phase) in coordinator.py
#   - Raft state machine (leader election + log replication) in raft_node.py
#   - NODE_ID environment variable read below to identify this node in
#     all protocol print statements required by the assignment.
# =============================================================================

import grpc
from concurrent import futures
import time
import os
import psycopg2
import psycopg2.pool
import sys

sys.path.insert(0, '/app/proto')
import pharmacy_pb2
import pharmacy_pb2_grpc

DB_HOST = os.environ.get("DB_HOST", "db-primary")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "pharmacy")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "postgres")

# [PROJECT 3] NODE_ID identifies this container in 2PC and Raft print statements.
# Set via environment variable in docker-compose.yml (1–5 for api-server-a through e).
NODE_ID = int(os.environ.get("NODE_ID", "0"))

def get_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )

def init_db():
    for i in range(10):
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS drugs (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    price FLOAT NOT NULL DEFAULT 0.0,
                    expiry_date VARCHAR(50),
                    category VARCHAR(100)
                )
            """)
            conn.commit()
            cur.close()
            conn.close()
            print("Database initialized successfully")
            return
        except Exception as e:
            print(f"DB init attempt {i+1} failed: {e}")
            time.sleep(3)
    raise Exception("Could not connect to database after 10 attempts")

class PharmacyServicer(pharmacy_pb2_grpc.PharmacyServiceServicer):

    def AddDrug(self, request, context):
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO drugs (name, quantity, price, expiry_date, category) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (request.name, request.quantity, request.price, request.expiry_date, request.category)
            )
            drug_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            drug = pharmacy_pb2.Drug(
                id=drug_id, name=request.name, quantity=request.quantity,
                price=request.price, expiry_date=request.expiry_date, category=request.category
            )
            return pharmacy_pb2.DrugResponse(success=True, message="Drug added", drug=drug)
        except Exception as e:
            return pharmacy_pb2.DrugResponse(success=False, message=str(e))

    def GetDrug(self, request, context):
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, name, quantity, price, expiry_date, category FROM drugs WHERE id=%s", (request.id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row:
                return pharmacy_pb2.DrugResponse(success=False, message="Drug not found")
            drug = pharmacy_pb2.Drug(id=row[0], name=row[1], quantity=row[2], price=row[3], expiry_date=row[4], category=row[5])
            return pharmacy_pb2.DrugResponse(success=True, message="Found", drug=drug)
        except Exception as e:
            return pharmacy_pb2.DrugResponse(success=False, message=str(e))

    def UpdateStock(self, request, context):
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("UPDATE drugs SET quantity=%s WHERE id=%s RETURNING id, name, quantity, price, expiry_date, category", (request.quantity, request.id))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            if not row:
                return pharmacy_pb2.DrugResponse(success=False, message="Drug not found")
            drug = pharmacy_pb2.Drug(id=row[0], name=row[1], quantity=row[2], price=row[3], expiry_date=row[4], category=row[5])
            return pharmacy_pb2.DrugResponse(success=True, message="Stock updated", drug=drug)
        except Exception as e:
            return pharmacy_pb2.DrugResponse(success=False, message=str(e))

    def DeleteDrug(self, request, context):
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM drugs WHERE id=%s RETURNING id", (request.id,))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            if not row:
                return pharmacy_pb2.DeleteResponse(success=False, message="Drug not found")
            return pharmacy_pb2.DeleteResponse(success=True, message=f"Drug {request.id} deleted")
        except Exception as e:
            return pharmacy_pb2.DeleteResponse(success=False, message=str(e))

    def ListDrugs(self, request, context):
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, name, quantity, price, expiry_date, category FROM drugs ORDER BY id")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            drugs = [pharmacy_pb2.Drug(id=r[0], name=r[1], quantity=r[2], price=r[3], expiry_date=r[4], category=r[5]) for r in rows]
            return pharmacy_pb2.ListDrugsResponse(drugs=drugs)
        except Exception as e:
            return pharmacy_pb2.ListDrugsResponse(drugs=[])

    def GetLowStock(self, request, context):
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, name, quantity, price, expiry_date, category FROM drugs WHERE quantity <= %s ORDER BY quantity", (request.threshold,))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            drugs = [pharmacy_pb2.Drug(id=r[0], name=r[1], quantity=r[2], price=r[3], expiry_date=r[4], category=r[5]) for r in rows]
            return pharmacy_pb2.ListDrugsResponse(drugs=drugs)
        except Exception as e:
            return pharmacy_pb2.ListDrugsResponse(drugs=[])

def serve():
    init_db()

    # -------------------------------------------------------------------------
    # ORIGINAL: PharmacyService on port 50051
    # -------------------------------------------------------------------------
    pharmacy_server = grpc.server(futures.ThreadPoolExecutor(max_workers=50))
    pharmacy_pb2_grpc.add_PharmacyServiceServicer_to_server(PharmacyServicer(), pharmacy_server)
    pharmacy_server.add_insecure_port('[::]:50051')
    pharmacy_server.start()
    print(f"gRPC PharmacyService started on port 50051 (Node {NODE_ID})")

    # [PROJECT 3] TwoPhaseParticipantService on port 50052 — runs on all 5 nodes.
    # Handles VoteRequest (Q1) and GlobalCommit/GlobalAbort (Q2).
    from participant import TwoPhaseParticipantServicer
    participant_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pharmacy_pb2_grpc.add_TwoPhaseParticipantServiceServicer_to_server(
        TwoPhaseParticipantServicer(), participant_server
    )
    participant_server.add_insecure_port('[::]:50052')
    participant_server.start()
    print(f"[PROJECT 3] TwoPhaseParticipantService started on port 50052 (Node {NODE_ID})")

    # [PROJECT 3] CoordinatorService on port 50053 — runs ONLY on Node 1.
    # Receives UpdateStock2PC from the client and drives the full 2PC protocol.
    # Node 1 calls its own participant service on localhost:50052 via gRPC,
    # which satisfies the assignment requirement for intra-node gRPC communication
    # between the voting phase and the decision phase.
    if NODE_ID == 1:
        from coordinator import serve_coordinator
        coord_server = serve_coordinator()  # [PROJECT 3] keep reference alive; GC would stop it otherwise

    pharmacy_server.wait_for_termination()

if __name__ == '__main__':
    serve()
