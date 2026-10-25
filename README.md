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
   - Build and launch the containerized stack (MongoDB Replica Set with auth & GridFS, FastAPI Backend, Vite Frontend).
   - Wait for `/health` to report `healthy`.

---

## Running the Application

### Start the Full Stack (Docker)
All published ports are strictly bound to `127.0.0.1` for local isolation.
```powershell
docker compose up -d
```

### Access Points
- **Frontend App:** http://127.0.0.1:5173
- **Backend Health Check:** http://127.0.0.1:8000/health
- **FastAPI OpenAPI Docs:** http://127.0.0.1:8000/docs
- **Image Storage:** Internal MongoDB GridFS (served only via authenticated backend endpoints)

### Stop the Stack
```powershell
docker compose down
```

### Reset Local Volumes & Databases
To wipe local development MongoDB replica set data, keyfiles, and GridFS images:
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
*(Executes pytest inside the backend container against an isolated replica set test database, testing health, transaction rollback/commit atomicity, and GridFS save/open/delete operations).*

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
