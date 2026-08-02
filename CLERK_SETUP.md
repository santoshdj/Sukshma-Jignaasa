# Clerk Authentication Setup Guide

This guide walks you through setting up Clerk authentication for the Sukshma-Jignaasa app with default patient credentials.

## 1. Create a Clerk Account

1. Go to [https://dashboard.clerk.com/sign-up](https://dashboard.clerk.com/sign-up)
2. Sign up for a free account
3. Verify your email

## 2. Create a New Application

1. Click "Add application" in the Clerk Dashboard
2. Application name: `Sukshma-Jignaasa` (or your preferred name)
3. Select "Next.js" as the framework
4. Click "Create application"

## 3. Get Your API Keys

After creating the application, you'll see your API keys:

1. Copy the **Publishable Key** (starts with `pk_test_...`)
2. Copy the **Secret Key** (starts with `sk_test_...`)
3. Add these to `frontend/.env.local`:

```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_key_here
CLERK_SECRET_KEY=sk_test_your_key_here
```

## 4. Configure Clerk Settings

### Email & Password Authentication

1. In Clerk Dashboard, go to **User & Authentication** → **Email, Phone, Username**
2. Enable **Email address** as a required field
3. Enable **Password** authentication
4. Save changes

### Social Sign-In (Optional)

You can also enable Google, GitHub, or other OAuth providers:
1. Go to **User & Authentication** → **Social connections**
2. Enable desired providers (e.g., Google)
3. Follow provider-specific setup instructions

### Session Settings

1. Go to **Sessions**
2. Set session duration (default: 7 days is fine)
3. Enable **Multi-session handling** if you want users to stay logged in across devices

## 5. Create Default Patient User

### Option A: Manual Creation via Dashboard

1. Go to **Users** in Clerk Dashboard
2. Click **Create user**
3. Fill in the details:
   - **Email**: `patient@demo.com`
   - **Password**: `Demo123!@#` (or your preferred password)
   - **First name**: `Demo`
   - **Last name**: `Patient`
4. Click **Create**
5. The user ID (e.g., `user_2abc123xyz`) will be used as `patient_id` in the backend

### Option B: Self-Registration

1. Run the app: `npm run dev` in the `frontend/` directory
2. Go to [http://localhost:3000/sign-up](http://localhost:3000/sign-up)
3. Create an account with:
   - **Email**: `patient@demo.com`
   - **Password**: `Demo123!@#`
   - **First name**: `Demo`
   - **Last name**: `Patient`
4. Verify email (check your inbox or use Clerk's test mode)

## 6. Test the Authentication Flow

### Sign In

1. Go to [http://localhost:3000](http://localhost:3000)
2. You'll be redirected to `/sign-in`
3. Enter credentials:
   - **Email**: `patient@demo.com`
   - **Password**: `Demo123!@#`
4. You'll be redirected back to the home page
5. You should see the user button in the top-right corner

### Sign Out

1. Click the user button (avatar) in the top-right
2. Click **Sign out**
3. You'll be redirected to `/sign-in`

## 7. Advanced Configuration

### Custom User Metadata

You can add custom metadata to users for patient-specific data:

1. Go to **Users** → Select a user
2. Click **Metadata** tab
3. Add public metadata (visible to frontend):
   ```json
   {
     "patientType": "demo",
     "conditionTracking": ["diabetes", "rare-disease"]
   }
   ```
4. Access in frontend: `user.publicMetadata.patientType`

### Webhook Integration (Optional)

To sync Clerk users with your backend database:

1. Go to **Webhooks** in Clerk Dashboard
2. Add endpoint: `https://your-backend-url.com/api/webhooks/clerk`
3. Select events: `user.created`, `user.updated`, `user.deleted`
4. Copy the signing secret
5. Add to backend `.env`:
   ```env
   CLERK_WEBHOOK_SECRET=whsec_your_secret_here
   ```

## 8. Default Patient Credentials Summary

For testing and demo purposes, use these credentials:

| Field | Value |
|-------|-------|
| **Email** | `patient@demo.com` |
| **Password** | `Demo123!@#` |
| **First Name** | `Demo` |
| **Last Name** | `Patient` |

**Security Note**: Change these credentials in production or disable this account and create real patient accounts.

## 9. Railway Deployment

When deploying to Railway, add these environment variables to the **frontend service**:

```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_key_here
CLERK_SECRET_KEY=sk_test_your_key_here
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/
```

## 10. Troubleshooting

### "Clerk: Missing publishable key"

- Ensure `.env.local` exists in `frontend/` directory
- Verify `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is set correctly
- Restart the dev server: `npm run dev`

### "Invalid redirect URL"

- In Clerk Dashboard, go to **Paths**
- Add your development URL: `http://localhost:3000`
- Add your production URL: `https://your-app.railway.app`

### "Session expired" errors

- Check session duration in Clerk Dashboard → **Sessions**
- Clear browser cookies and sign in again

### User button not showing

- Verify `@clerk/nextjs` is installed: `npm list @clerk/nextjs`
- Check console for errors
- Ensure `ClerkProvider` wraps your app in `layout.tsx`

## 11. Next Steps

- **Backend Integration**: Add Clerk JWT validation to FastAPI endpoints
- **User-to-Patient Mapping**: Create a `users` table in PostgreSQL mapping Clerk user IDs to patient records
- **RBAC**: Use Clerk organizations and roles for clinician vs patient access
- **Multi-factor Authentication**: Enable 2FA in Clerk Dashboard for production

---

For more information, see [Clerk Documentation](https://clerk.com/docs).
