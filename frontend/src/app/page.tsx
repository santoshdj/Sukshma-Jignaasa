export default function HomePage() {
  return (
    <main className="max-w-lg mx-auto px-4 py-16 text-center">
      <h1 className="text-3xl font-bold text-slate-800 mb-3">सूक्ष्म जिज्ञासा</h1>
      <p className="text-slate-500 mb-8">Your AI companion for rare disease pattern tracking.</p>
      <a
        href="/check-in"
        className="inline-block bg-brand-600 hover:bg-brand-700 text-white font-semibold px-6 py-3 rounded-xl transition-colors"
      >
        Log today →
      </a>
    </main>
  );
}
