import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-slate-800 mb-2">सूक्ष्म जिज्ञासा</h1>
          <p className="text-xs font-medium text-slate-400 tracking-widest uppercase">
            Sukshma Jijñāsā · The Subtle Inquiry
          </p>
          <p className="text-slate-600 mt-4">Create your account to begin tracking</p>
        </div>
        <div className="flex justify-center">
          <SignUp 
            appearance={{
              elements: {
                rootBox: "w-full",
                card: "shadow-xl",
              },
            }}
          />
        </div>
      </div>
    </div>
  );
}
