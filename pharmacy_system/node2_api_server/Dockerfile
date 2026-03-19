FROM python:3.11-slim

WORKDIR /app

# Unbuffered Python output so Docker logs capture print() statements immediately
ENV PYTHONUNBUFFERED=1

RUN pip install grpcio grpcio-tools psycopg2-binary --no-cache-dir

COPY proto/pharmacy.proto /app/proto/pharmacy.proto

RUN python -m grpc_tools.protoc \
    -I/app/proto \
    --python_out=/app/proto \
    --grpc_python_out=/app/proto \
    /app/proto/pharmacy.proto

COPY node2_api_server/server.py /app/server.py

# [PROJECT 3] Copy 2PC participant and coordinator modules
COPY node2_api_server/participant.py /app/participant.py
COPY node2_api_server/coordinator.py /app/coordinator.py

# Expose all service ports:
#   50051 — original PharmacyService
#   50052 — [PROJECT 3] TwoPhaseParticipantService (all nodes)
#   50053 — [PROJECT 3] CoordinatorService (Node 1 only)
EXPOSE 50051 50052 50053

CMD ["python", "/app/server.py"]
