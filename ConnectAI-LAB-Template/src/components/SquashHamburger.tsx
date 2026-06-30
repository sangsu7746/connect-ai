import { motion } from 'framer-motion';

interface SquashHamburgerProps {
  isOpen: boolean;
  isMobile?: boolean;
}

export function SquashHamburger({ isOpen, isMobile = false }: SquashHamburgerProps) {
  const containerW = isMobile ? 15 : 18;
  const containerH = isMobile ? 10 : 12;
  const barH = isMobile ? 1.2 : 1.5;
  const centerY = containerH / 2 - barH / 2;

  return (
    <div className="relative" style={{ width: containerW, height: containerH }}>
      {/* Top bar */}
      <motion.span
        className="absolute left-0 right-0 bg-white rounded-full"
        style={{ height: barH, top: 0 }}
        animate={
          isOpen
            ? { rotate: 45, y: centerY }
            : { rotate: 0, y: 0 }
        }
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      />
      {/* Middle bar */}
      <motion.span
        className="absolute left-0 right-0 bg-white rounded-full"
        style={{ height: barH, top: centerY }}
        animate={
          isOpen
            ? { opacity: 0, scaleX: 0 }
            : { opacity: 1, scaleX: 1 }
        }
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      />
      {/* Bottom bar */}
      <motion.span
        className="absolute left-0 right-0 bg-white rounded-full"
        style={{ height: barH, bottom: 0 }}
        animate={
          isOpen
            ? { rotate: -45, y: -centerY }
            : { rotate: 0, y: 0 }
        }
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      />
    </div>
  );
}
