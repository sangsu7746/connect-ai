import Header from '@/components/Header';
import Hero from '@/components/Hero';
import StyleGallery from '@/components/StyleGallery';
import HowItWorks from '@/components/HowItWorks';
import Studio from '@/components/Studio';
import Pricing from '@/components/Pricing';
import Faq from '@/components/Faq';
import Footer from '@/components/Footer';

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="flex-1">
        <Hero />
        <StyleGallery />
        <HowItWorks />
        <Studio />
        <Pricing />
        <Faq />
      </main>
      <Footer />
    </div>
  );
}
