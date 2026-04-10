export default function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`bg-linear-to-r from-(--muted)/40 via-(--muted)/70 to-(--muted)/40 animate-shimmer rounded-xl ${className}`}
    />
  );
}
