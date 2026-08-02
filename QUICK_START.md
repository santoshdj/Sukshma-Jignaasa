# 🚀 Quick Start - Clerk Authentication

## TL;DR

**Default Credentials:**
- Email: `patient@demo.com`
- Password: `Demo123!@#`

## 5-Minute Setup

### 1. Get Clerk API Keys (2 min)

```bash
# 1. Go to https://dashboard.clerk.com/sign-up
# 2. Create account
# 3. Click "Add application" → Name: "Sukshma-Jignaasa"
# 4. Copy your keys:
#    - Publishable Key (pk_test_...)
#    - Secret Key (sk_test_...)
```

### 2. Configure Frontend (1 min)

```bash
cd frontend

# Create .env.local file
cat > .env.local << 'EOF'
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_YOUR_KEY_HERE
CLERK_SECRET_KEY=sk_test_YOUR_KEY_HERE
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/
BACKEND_URL=http://localhost:8000
EOF

# Install and run
npm install
npm run dev
```

### 3. Start Backend (1 min)

```bash
cd backend

# Activate venv and run
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux

uvicorn main:app --reload
```

### 4. Create Test User (1 min)

**Option A: Via Dashboard**
- Go to https://dashboard.clerk.com → Users → Create user
- Email: `patient@demo.com`, Password: `Demo123!@#`

**Option B: Via App**
- Go to http://localhost:3000/sign-up
- Sign up with `patient@demo.com`

### 5. Test (30 sec)

```bash
# Open browser
http://localhost:3000

# Sign in with patient@demo.com / Demo123!@#
# You should see:
# - Your name in top-right
# - User button with logout
# - EHR connection status
```

## Troubleshooting

### "Clerk: Missing publishable key"
```bash
# Ensure .env.local exists in frontend/
ls frontend/.env.local

# Restart dev server
npm run dev
```

### "401 Unauthorized"
- Check backend is running: http://localhost:8000/health
- Sign out and sign in again

### "Connection failed" (EHR)
- Verify Medblocks credentials in `backend/.env`

## What Was Installed

### Frontend
- ✅ `@clerk/nextjs@5.7.2` package
- ✅ Login/logout pages at `/sign-in` and `/sign-up`
- ✅ Auth middleware protecting all routes
- ✅ User button with profile dropdown
- ✅ Patient ID fetching from backend

### Backend
- ✅ `/users/me` endpoint for user-to-patient mapping
- ✅ `UserRow` database model
- ✅ Clerk JWT validation utilities

## Next Steps

- **Production**: See [CLERK_SETUP.md](./CLERK_SETUP.md) section 11
- **Security**: Implement JWT signature validation in `backend/app/auth.py`
- **Features**: Enable 2FA, add social sign-in, webhooks

## File Locations

```
frontend/
├── .env.local                    # Your Clerk keys
├── src/app/layout.tsx            # ClerkProvider
├── src/app/sign-in/              # Login page
├── src/app/sign-up/              # Registration page
└── src/middleware.ts             # Route protection

backend/
├── app/auth.py                   # JWT validation
├── app/routers/users.py          # User endpoints
└── app/db/models.py              # UserRow model
```

## API Examples

### Get Current User
```bash
# Get Clerk token (from browser dev tools → Application → Cookies → __session)
TOKEN="your_clerk_session_token"

# Call backend
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/users/me

# Response:
{
  "patient_id": "550e8400-e29b-41d4-a716-446655440000",
  "clerk_user_id": "user_2abc123xyz",
  "email": "patient@demo.com",
  "first_name": "Demo",
  "last_name": "Patient"
}
```

---

**For complete documentation, see:**
- [CLERK_SETUP.md](./CLERK_SETUP.md) - Full setup guide
- [README.md](./README.md) - Main project docs
- [docs/CLERK_IMPLEMENTATION.md](./docs/CLERK_IMPLEMENTATION.md) - Implementation details
