# ONCOLINK

*College portfolio research prototype. Version 2, consolidated after comparison with real-world oral cancer screening programs. Not a medical device.*

> **Intended Use Statement:** ONCOLINK is a research and education prototype. It is not a medical device, does not diagnose cancer, and must not be used for clinical decisions. Only a biopsy can confirm oral cancer. All data comes from public datasets and consenting volunteers.

---

## Prerequisites

- **Windows 10/11** with PowerShell
- **Docker Desktop** (WSL2 engine enabled and running)
- **Node.js LTS** (v22 or newer) and `npm`
- **Python 3.11** or newer
- **Git**

---

## First-Time Setup

1. Open PowerShell and navigate to the project directory:
   ```powershell
   Set-Location "C:\OncoLink"
   ```

2. Run the automated setup script:
   ```powershell
   .\scripts\setup.ps1
   ```
   This will:
   - Verify all prerequisites.
   - Generate `.env` from `.env.example` if not already present.
   - Install frontend packages.
   - Build and launch the containerized stack (MongoDB Replica Set with auth, MinIO, FastAPI Backend, Vite Frontend).
   - Wait for `/health` to report `healthy`.

---

## Running the Application

### Start the Full Stack (Docker)
```powershell
docker compose up -d
```

### Access Points
- **Frontend App:** http://localhost:5173
- **Backend Health Check:** http://localhost:8000/health
- **FastAPI OpenAPI Docs:** http://localhost:8000/docs
- **MinIO Storage Console:** http://localhost:9001

### Stop the Stack
```powershell
docker compose down
```

### Reset Local Volumes & Databases
To wipe local development MongoDB replica set data and MinIO buckets:
```powershell
.\scripts\reset-docker.ps1
```

---

## Testing & Quality Assurance

All commands can be executed using `npm` from PowerShell:

### Run All Tests
```powershell
npm run test
```

### Run Backend Tests Only
```powershell
npm run test:backend
```
*(Executes pytest inside the backend container against an isolated replica set test database, including transaction atomicity and rollback verification).*

### Run Frontend Smoke Tests
```powershell
npm run test:frontend
```

---

## Linting & Type Checking

### Run All Linters
```powershell
npm run lint
```

### Backend Linting (Ruff)
```powershell
npm run lint:backend
```

### Frontend Linting & Typecheck (ESLint & TypeScript)
```powershell
npm run lint:frontend
npm run typecheck
```

---

## Architecture Decisions

Authoritative domain and technical decisions are documented in [docs/DECISIONS.md](docs/DECISIONS.md).  
Detailed behavior is in [docs/SPEC.md](docs/SPEC.md) and interface guidelines are in [docs/DESIGN.md](docs/DESIGN.md).
