import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ConnectAILabLogo } from './ConnectAILabLogo';
import { SquashHamburger } from './SquashHamburger';
import { ScrambleText } from './ScrambleText';
import { AuthModal } from './AuthModal';
import { useAuth } from '../contexts/AuthContext';
import { SITE_CONFIG } from '../config/content';

interface NavbarProps {
  entranceComplete: boolean;
}

export function Navbar({ entranceComplete }: NavbarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [downloadHovered, setDownloadHovered] = useState(false);
  const [aboutHovered, setAboutHovered] = useState(false);
  const [metricsHovered, setMetricsHovered] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const { user, signOut } = useAuth();

  const scrollTo = (y: number) => {
    window.scrollTo({ top: y, behavior: 'smooth' });
    setMenuOpen(false);
  };

  return (
    <>
      <motion.nav
        className="fixed top-0 left-0 right-0 z-50 h-20 flex items-center px-4 sm:px-6 md:px-8"
        initial={{ opacity: 0 }}
        animate={{ opacity: entranceComplete ? 1 : 0 }}
        transition={{ duration: 0.8 }}
      >
        {/* ===== DESKTOP ===== */}
        <div className="hidden sm:flex items-center justify-between w-full">
          {/* Left group */}
          <div className="flex items-center gap-2">
            {/* Logo pill */}
            <motion.div
              className={`h-12 px-5 bg-white/15 backdrop-blur-md rounded-[14px] flex items-center gap-2.5 cursor-pointer ${
                menuOpen ? 'hidden md:flex' : 'flex'
              }`}
              whileHover={{ scale: 1.02, backgroundColor: 'rgba(255,255,255,0.22)' }}
              whileTap={{ scale: 0.98 }}
            >
              <ConnectAILabLogo size={18} className="text-white" />
              <span className="text-[16px] font-medium tracking-tight text-white">
                {SITE_CONFIG.brandName}
              </span>
            </motion.div>

            {/* Expanding menu pill */}
            <motion.div
              className="h-12 rounded-[14px] bg-white/15 backdrop-blur-md flex items-center overflow-hidden"
              animate={{ width: menuOpen ? 290 : 48 }}
              transition={{ type: 'spring', stiffness: 350, damping: 28 }}
            >
              {/* Hamburger button */}
              <motion.button
                className="flex items-center justify-center shrink-0 cursor-pointer"
                style={{
                  width: menuOpen ? 36 : 48,
                  height: menuOpen ? 36 : 48,
                  borderRadius: menuOpen ? 11 : 14,
                  backgroundColor: menuOpen ? 'rgba(255,255,255,0.1)' : 'transparent',
                  marginLeft: menuOpen ? 6 : 0,
                }}
                onClick={() => setMenuOpen(!menuOpen)}
                whileHover={{ backgroundColor: menuOpen ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.1)' }}
              >
                <SquashHamburger isOpen={menuOpen} />
              </motion.button>

              {/* Nav links */}
              <AnimatePresence>
                {menuOpen && (
                  <motion.div
                    className="flex items-center gap-6 ml-4 whitespace-nowrap"
                    initial={{ opacity: 0, x: 15 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 15 }}
                    transition={{ duration: 0.25 }}
                  >
                    <button
                      className="text-[16px] font-normal text-white/85 hover:text-white transition-colors cursor-pointer bg-transparent border-none"
                      onMouseEnter={() => setAboutHovered(true)}
                      onMouseLeave={() => setAboutHovered(false)}
                      onClick={() => scrollTo(window.innerHeight)}
                    >
                      <ScrambleText text="About" isHovered={aboutHovered} />
                    </button>
                    <button
                      className="text-[16px] font-normal text-white/85 hover:text-white transition-colors cursor-pointer bg-transparent border-none"
                      onMouseEnter={() => setMetricsHovered(true)}
                      onMouseLeave={() => setMetricsHovered(false)}
                      onClick={() => scrollTo(window.innerHeight * 2)}
                    >
                      <ScrambleText text="Metrics" isHovered={metricsHovered} />
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </div>

          {/* Right buttons */}
          <div className="flex items-center gap-2">
            {/* Sign In / User button */}
            {user ? (
              <div className="flex items-center gap-2">
                <div className="h-12 px-5 bg-white/10 backdrop-blur-md rounded-[14px] flex items-center gap-3">
                  {user.photoURL ? (
                    <img
                      src={user.photoURL}
                      alt=""
                      className="w-7 h-7 rounded-full object-cover"
                    />
                  ) : (
                    <div className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center text-white text-[12px] font-bold">
                      {(user.displayName?.[0] || user.email?.[0] || 'U').toUpperCase()}
                    </div>
                  )}
                  <span className="text-[14px] text-white/80 max-w-[120px] truncate">
                    {user.displayName || user.email?.split('@')[0] || 'User'}
                  </span>
                  <button
                    onClick={signOut}
                    className="text-[12px] text-white/40 hover:text-white/80 transition-colors cursor-pointer bg-transparent border-none ml-1"
                  >
                    Sign Out
                  </button>
                </div>
              </div>
            ) : (
              <motion.button
                className="h-12 px-5 bg-white/10 backdrop-blur-md rounded-[14px] flex items-center gap-2 cursor-pointer border-none text-white/85 text-[15px] font-medium hover:bg-white/20 transition-colors"
                whileTap={{ scale: 0.97 }}
                onClick={() => setAuthOpen(true)}
              >
                Sign In
              </motion.button>
            )}

            {/* Download button */}
            <motion.button
              className="h-12 px-6 bg-white rounded-full flex items-center gap-2.5 cursor-pointer border-none"
              whileHover={{ scale: 1.03, backgroundColor: '#e2e2e6' }}
              whileTap={{ scale: 0.97 }}
              onMouseEnter={() => setDownloadHovered(true)}
              onMouseLeave={() => setDownloadHovered(false)}
            >
              <i className="bi bi-apple text-black text-[16px]" />
              <span className="text-black text-[16px] font-medium">
                <ScrambleText text="Download" isHovered={downloadHovered} />
              </span>
            </motion.button>
          </div>
        </div>

        {/* ===== MOBILE ===== */}
        <div className="flex sm:hidden items-center justify-between w-full">
          {/* Left group */}
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            {/* Logo pill (collapses when menu open) */}
            <motion.div
              className="h-9 px-3 bg-white/15 backdrop-blur-md rounded-[10px] flex items-center gap-2 overflow-hidden shrink-0"
              animate={{ width: menuOpen ? 0 : 'auto', opacity: menuOpen ? 0 : 1, paddingLeft: menuOpen ? 0 : 12, paddingRight: menuOpen ? 0 : 12 }}
              transition={{ type: 'spring', stiffness: 350, damping: 28 }}
            >
              <ConnectAILabLogo size={14} className="text-white shrink-0" />
              <span className="text-[13px] font-medium tracking-tight text-white whitespace-nowrap">
                {SITE_CONFIG.brandName}
              </span>
            </motion.div>

            {/* Expanding menu capsule */}
            <motion.div
              className="h-9 rounded-[10px] bg-white/15 backdrop-blur-md flex items-center overflow-hidden"
              animate={{ width: menuOpen ? '100%' : 36 }}
              transition={{ type: 'spring', stiffness: 350, damping: 28 }}
            >
              <motion.button
                className="flex items-center justify-center shrink-0 cursor-pointer"
                style={{
                  width: menuOpen ? 30 : 36,
                  height: menuOpen ? 30 : 36,
                  borderRadius: menuOpen ? 8 : 10,
                  backgroundColor: menuOpen ? 'rgba(255,255,255,0.1)' : 'transparent',
                  marginLeft: menuOpen ? 4 : 0,
                }}
                onClick={() => setMenuOpen(!menuOpen)}
              >
                <SquashHamburger isOpen={menuOpen} isMobile />
              </motion.button>

              <AnimatePresence>
                {menuOpen && (
                  <motion.div
                    className="flex items-center gap-4 ml-3 whitespace-nowrap"
                    initial={{ opacity: 0, x: 10 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 10 }}
                    transition={{ duration: 0.2 }}
                  >
                    <button
                      className="text-[13px] font-normal text-white/85 cursor-pointer bg-transparent border-none"
                      onClick={() => scrollTo(window.innerHeight)}
                    >
                      About
                    </button>
                    <button
                      className="text-[13px] font-normal text-white/85 cursor-pointer bg-transparent border-none"
                      onClick={() => scrollTo(window.innerHeight * 2)}
                    >
                      Metrics
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </div>

          {/* Right buttons */}
          <div className="flex items-center gap-1.5 ml-2">
            {/* Sign In / Avatar */}
            {user ? (
              <motion.button
                className="h-9 w-9 rounded-full bg-white/15 backdrop-blur-md flex items-center justify-center cursor-pointer border-none overflow-hidden"
                whileTap={{ scale: 0.9 }}
                onClick={signOut}
              >
                {user.photoURL ? (
                  <img src={user.photoURL} alt="" className="w-full h-full object-cover" />
                ) : (
                  <span className="text-white text-[12px] font-bold">
                    {(user.displayName?.[0] || user.email?.[0] || 'U').toUpperCase()}
                  </span>
                )}
              </motion.button>
            ) : (
              <motion.button
                className="h-9 px-3 bg-white/15 backdrop-blur-md rounded-[10px] flex items-center cursor-pointer border-none text-white/85 text-[12px] font-medium"
                whileTap={{ scale: 0.95 }}
                onClick={() => setAuthOpen(true)}
              >
                Sign In
              </motion.button>
            )}

            {/* Download button */}
            <motion.button
              className="h-9 px-3.5 bg-white rounded-full flex items-center gap-1.5 cursor-pointer border-none shrink-0"
              whileTap={{ scale: 0.95 }}
            >
              <i className="bi bi-apple text-black text-[13px]" />
              <span className="text-black text-[13px] font-medium">Download</span>
            </motion.button>
          </div>
        </div>
      </motion.nav>

      {/* Auth Modal */}
      <AuthModal isOpen={authOpen} onClose={() => setAuthOpen(false)} />
    </>
  );
}
