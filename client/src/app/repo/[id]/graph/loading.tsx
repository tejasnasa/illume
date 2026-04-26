export default function GraphLoading() {
  return (
    <main className="backdrop-blur-xs relative w-full h-[calc(100vh-64px)] flex flex-col items-center justify-center overflow-hidden">
      <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="w-8 h-8 rounded-full border-2 border-(--primary) border-t-transparent animate-spin mb-3" />
      </div>
    </main>
  );
}
