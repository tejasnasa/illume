import BackgroundGraph from "@/components/BackgroundGraph";

export default function Repository() {
  return (
    <main className="relative min-h-screen flex items-center justify-center">
      <BackgroundGraph />

      <div className="bg-(--card)/50 text-xl backdrop-blur-xs border rounded-sm p-4">
        <h1 className="text-(--foreground)">Hello</h1>
      </div>
    </main>
  );
}
