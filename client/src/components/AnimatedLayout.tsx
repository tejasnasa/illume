/**
 * Route-transition wrapper with slide-and-fade page animation.
 * @module AnimatedLayout
 */
"use client";

import { motion } from "motion/react";
import { usePathname } from "next/navigation";

/**
 * Wraps page content in a motion container keyed by route.
 *
 * @param children - React subtree to animate on route change.
 * @returns Animated wrapper that replays its entrance on navigation.
 */
export default function AnimatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <motion.div
      key={pathname}
      initial={{ x: 40, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 1, ease: [0.32, 0.72, 0, 1] }}
      className="h-full w-full"
    >
      {children}
    </motion.div>
  );
}
