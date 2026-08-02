# Sukshma-Jignaasa (सूक्ष्म जिज्ञासा)

**The Subtle Inquiry** - AI companion for rare disease pattern detection and tracking.

## Overview

Sukshma-Jignaasa is a healthcare application that helps patients track symptoms and detect patterns related to rare diseases. It integrates with Electronic Health Records (EHR) via Medblocks and uses AI to identify potential correlations and generate actionable insights.

## Tech Stack

### Frontend
- **Next.js 14** with TypeScript
- **Clerk** for authentication
- **Tailwind CSS** for styling
- **Zustand** for state management

### Backend
- **FastAPI** (Python 3.12)
- **PostgreSQL** with SQLAlchemy ORM
- **Medblocks** for FHIR/EHR integration
- **Claude** (Anthropic) for AI analysis
- **LiteLLM** for LLM routing

## Quick Start

### Prerequisites

- **Node.js 18+** (for frontend)
- **Python 3.12+** (for backend)
- **PostgreSQL** (or use SQLite for local development)
- **Clerk Account** (free at [clerk.com](https://clerk.com))
- **Medblocks API Key** (from [app.medblocks.com](https://app.medblocks.com))

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Sukshma-Jignaasa
```

### 2. Set Up Clerk Authentication

Follow the detailed guide in [CLERK_SETUP.md](./CLERK_SETUP.md) to:
1. Create a Clerk account and application
2. Get your API keys
3. Configure environment variables
4. Create a default patient user

**Quick setup:**

1. Sign up at [https://dashboard.clerk.com/sign-up](https://dashboard.clerk.com/sign-up)
2. Create a new application
3. Copy your API keys to `frontend/.env.local`:

```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_key_here
CLERK_SECRET_KEY=sk_test_your_key_here
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Copy environment template
cp .env.example .env.local

# Edit .env.local and add your Clerk keys (from step 2)

# Run development server
npm run dev
```

The frontend will be available at [http://localhost:3000](http://localhost:3000).

### 4. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env and add your credentials:
# - MEDBLOCKS_API_KEY
# - MEDBLOCKS_FHIR_BEARER_TOKEN
# - MEDBLOCKS_FHIR_BASE_URL
# - ANTHROPIC_API_KEY

# Run development server
uvicorn main:app --reload
```

The backend API will be available at [http://localhost:8000](http://localhost:8000).

### 5. Create Default Patient User

**Option A: Via Clerk Dashboard**
1. Go to [Clerk Dashboard](https://dashboard.clerk.com) → Users
2. Click "Create user"
3. Email: `patient@demo.com`, Password: `Demo123!@#`

**Option B: Via Sign-Up Page**
1. Go to [http://localhost:3000/sign-up](http://localhost:3000/sign-up)
2. Create account with email `patient@demo.com`

### 6. Test the Application

1. Go to [http://localhost:3000](http://localhost:3000)
2. Sign in with `patient@demo.com` / `Demo123!@#`
3. You should see the dashboard with:
   - User button in top-right (with logout option)
   - EHR connection status
   - Navigation to check-in and hypothesis pages

## Features

### Authentication (Clerk)
- ✅ Email/password sign-in and sign-up
- ✅ User profile management
- ✅ Session persistence
- ✅ Secure logout
- ✅ Protected routes
- ✅ User-to-patient ID mapping

### EHR Integration (Medblocks)
- Connect to patient's EHR via Medblocks OAuth
- Pull FHIR records (Conditions, Observations, Medications, Allergies, Encounters)
- Sync health records to local database
- Display connection status

### Symptom Tracking
- Daily check-in flow with conversational AI
- Structured symptom logging (FHIR Observations)
- Trigger and severity tracking

### Pattern Analysis
- AI-powered hypothesis generation
- Symptom correlation detection
- Temporal pattern recognition
- Clinician-ready reports

## API Documentation

Once the backend is running, visit:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Key Endpoints

#### Authentication
- `GET /users/me` - Get current user and patient_id

#### EHR
- `POST /ehr/connect/start` - Start Medblocks OAuth flow
- `POST /ehr/connect/complete` - Complete OAuth and verify session
- `POST /ehr/sync` - Sync FHIR records from Medblocks
- `GET /ehr/status` - Get current EHR connection status

#### Check-In
- `POST /check-in/start` - Start symptom logging session
- `POST /check-in/message` - Send patient message
- `POST /check-in/confirm` - Confirm and save symptom log

#### Hypothesis
- `POST /hypothesis/start` - Generate hypothesis from symptoms
- `GET /hypothesis/{session_id}/status` - Get analysis status
- `POST /hypothesis/{session_id}/approve` - Approve hypothesis
- `GET /hypothesis/{session_id}/report` - Get clinician report

## Deployment

### Railway

See [DEPLOYMENT.md](./DEPLOYMENT.md) for Railway deployment instructions (coming soon).

**Key environment variables for Railway:**

**Frontend Service:**
```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
BACKEND_URL=https://your-backend.railway.app
```

**Backend Service:**
```env
MEDBLOCKS_API_KEY=mb_sk_sbx_...
MEDBLOCKS_FHIR_BASE_URL=https://fhir.medblocks.com/fhir/...
MEDBLOCKS_FHIR_BEARER_TOKEN=eyJhbG...
ANTHROPIC_API_KEY=sk-ant-...
FRONTEND_URL=https://your-frontend.railway.app
```

## Security Notes

- **Development**: The provided default credentials (`patient@demo.com`) are for testing only
- **Production**: 
  - Delete or disable default test users
  - Enable Clerk multi-factor authentication
  - Rotate all API keys
  - Use environment-specific Clerk applications (separate for dev/staging/prod)
  - Implement backend JWT validation (see `CLERK_SETUP.md` section 11)

## Troubleshooting

See [CLERK_SETUP.md](./CLERK_SETUP.md) section 10 for authentication troubleshooting.

**Common issues:**

- **"Clerk: Missing publishable key"**: Ensure `.env.local` exists and contains `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
- **"Connection failed" in EHR**: Check Medblocks credentials in backend `.env`
- **401 Unauthorized**: Sign out and sign back in to refresh session

## Project Structure

```
Sukshma-Jignaasa/
├── frontend/                 # Next.js frontend
│   ├── src/
│   │   ├── app/             # Next.js 14 App Router pages
│   │   │   ├── sign-in/     # Clerk sign-in page
│   │   │   ├── sign-up/     # Clerk sign-up page
│   │   │   ├── check-in/    # Symptom logging
│   │   │   ├── hypothesis/  # Pattern analysis
│   │   │   └── ehr/         # EHR connection
│   │   ├── components/      # React components
│   │   ├── lib/            # API clients
│   │   └── middleware.ts   # Clerk auth middleware
│   └── package.json
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── routers/        # API endpoints
│   │   ├── services/       # Business logic
│   │   ├── models/         # Pydantic models
│   │   ├── db/             # SQLAlchemy models
│   │   ├── agents/         # AI workflows
│   │   └── auth.py         # Clerk JWT validation
│   ├── main.py
│   └── requirements.txt
├── specs/                   # Feature specifications
├── CLERK_SETUP.md          # Detailed Clerk setup guide
└── README.md               # This file
```

## Documentation

- **[CLERK_SETUP.md](./CLERK_SETUP.md)** - Complete Clerk authentication setup
- **[TECH-STACK.md](./specs/TECH-STACK.md)** - Technical architecture details
- **[ROADMAP.md](./specs/ROADMAP.md)** - Feature roadmap

## License

[Add license here]

## Support

For issues and questions:
- Check [CLERK_SETUP.md](./CLERK_SETUP.md) for authentication issues
- Review API docs at `/docs` endpoint
- [Create an issue](https://github.com/your-repo/issues) in the repository

---

**सूक्ष्म जिज्ञासा** (Sukshma Jijñāsā) - Empowering patients with AI-driven rare disease insights.
