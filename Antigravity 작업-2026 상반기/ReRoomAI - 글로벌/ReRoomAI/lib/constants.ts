// Room types, design styles, generation modes and pricing
// (shared between client UI and server prompt builder)

export type GenerationMode = {
  id: string;
  label: string;
  desc: string;
  badge?: string;
  /** whether the room-type picker applies to this mode */
  needsRoomType: boolean;
  /** whether the style picker applies to this mode */
  needsStyle: boolean;
};

export type RoomType = {
  id: string;
  label: string;
  /** English noun used inside the Gemini prompt */
  prompt: string;
};

export type StyleOption = {
  id: string;
  label: string;
  desc: string;
  /** Representative color swatches shown on style cards */
  swatch: [string, string, string];
  /** Style directive injected into the Gemini prompt */
  prompt: string;
};

export type CreditPack = {
  id: string;
  label: string;
  credits: number;
  price: string;
  /** exact USD amount charged via PayPal (server-side source of truth) */
  usd: number;
  perImage: string;
  highlight?: boolean;
};

export const MODES: GenerationMode[] = [
  {
    id: "redesign",
    label: "Restyle My Room",
    desc: "Give a furnished room a completely new look",
    needsRoomType: true,
    needsStyle: true,
  },
  {
    id: "staging",
    label: "Virtual Staging",
    desc: "Furnish an empty room for listings & rentals",
    badge: "For Realtors",
    needsRoomType: true,
    needsStyle: true,
  },
  {
    id: "declutter",
    label: "Remove Furniture",
    desc: "Empty out an occupied or cluttered room",
    badge: "New",
    needsRoomType: true,
    needsStyle: false,
  },
  {
    id: "twilight",
    label: "Day to Dusk",
    desc: "Turn a daytime exterior into a twilight shot",
    badge: "New",
    needsRoomType: false,
    needsStyle: false,
  },
  {
    id: "renovation",
    label: "Renovation Preview",
    desc: "Preview new floors, cabinets & finishes",
    badge: "New",
    needsRoomType: true,
    needsStyle: true,
  },
  {
    id: "curb_appeal",
    label: "Curb Appeal",
    desc: "Refresh the lawn, landscaping & facade",
    badge: "New",
    needsRoomType: false,
    needsStyle: false,
  },
];

export const ROOM_TYPES: RoomType[] = [
  { id: "living_room", label: "Living Room", prompt: "living room" },
  { id: "bedroom", label: "Bedroom", prompt: "bedroom" },
  { id: "kitchen", label: "Kitchen", prompt: "kitchen" },
  { id: "bathroom", label: "Bathroom", prompt: "bathroom" },
  { id: "study", label: "Home Office", prompt: "home office / study room" },
  { id: "studio", label: "Studio Apt", prompt: "studio apartment" },
];

export const STYLES: StyleOption[] = [
  {
    id: "modern",
    label: "Modern",
    desc: "Clean lines, calm and composed",
    swatch: ["#2b2b2e", "#c9c9cd", "#8a6f52"],
    prompt:
      "sleek modern style: clean lines, neutral palette with charcoal and greige, low-profile furniture, matte finishes, statement lighting",
  },
  {
    id: "minimal",
    label: "Minimalist",
    desc: "The beauty of less",
    swatch: ["#f4f2ee", "#d8d4cc", "#9a958a"],
    prompt:
      "minimalist style: pared-down furnishings, warm white walls, hidden storage, soft diffuse light, generous negative space",
  },
  {
    id: "scandinavian",
    label: "Scandinavian",
    desc: "Warm, natural and cozy",
    swatch: ["#e9e2d5", "#b9a284", "#5f6f5e"],
    prompt:
      "Scandinavian style: light oak wood, cozy wool and linen textiles, white and sage accents, hygge atmosphere, potted greenery",
  },
  {
    id: "industrial",
    label: "Industrial",
    desc: "Concrete, steel and character",
    swatch: ["#4a4a4a", "#7d6a58", "#2f3540"],
    prompt:
      "industrial loft style: exposed concrete texture, black steel frames, leather and reclaimed wood furniture, Edison bulb lighting",
  },
  {
    id: "japandi",
    label: "Japandi",
    desc: "Eastern calm, Western function",
    swatch: ["#ded5c4", "#8c7b60", "#3d3a33"],
    prompt:
      "Japandi style: low wooden furniture, wabi-sabi ceramics, rice-paper lighting, muted earth tones, calm uncluttered balance",
  },
  {
    id: "mid_century",
    label: "Mid-Century",
    desc: "Retro colors and wood grain",
    swatch: ["#b0562f", "#e0b04e", "#3f5748"],
    prompt:
      "mid-century modern style: walnut furniture with tapered legs, mustard and teal accent colors, geometric patterns, retro lighting",
  },
  {
    id: "coastal",
    label: "Coastal",
    desc: "Airy, bright and relaxed",
    swatch: ["#e8f0f2", "#a9c3cb", "#c8b491"],
    prompt:
      "coastal style: breezy white and soft blue palette, natural rattan and light wood, linen slipcovered sofas, airy bright atmosphere",
  },
  {
    id: "hotel_lounge",
    label: "Luxury Hotel",
    desc: "Rich, grand and refined",
    swatch: ["#1f2430", "#9c8455", "#5c5148"],
    prompt:
      "luxury hotel lounge style: plush velvet seating, brass and marble details, layered ambient lighting, dark sophisticated palette",
  },
];

/** Builds the final instruction sent to Gemini for a given mode. */
export function buildInstruction(modeId: string, roomPrompt: string, stylePrompt: string): string {
  if (modeId === "staging") {
    return `Virtually stage this empty ${roomPrompt} in ${stylePrompt}. Keep the room architecture — walls, windows, doors, flooring, ceiling and camera perspective — exactly the same. Add realistic, tastefully arranged furniture, rugs, lighting, wall art and decor appropriate for a ${roomPrompt}. The result must look like professional MLS real-estate listing photography: photorealistic, natural lighting, high detail, no people.`;
  }
  if (modeId === "declutter") {
    return `Completely remove all furniture, rugs, curtains, wall art, personal items and clutter from this ${roomPrompt}, leaving it entirely empty. Keep the room architecture — walls, windows, doors, flooring, ceiling, built-in fixtures (cabinets, counters, radiators) and camera perspective — exactly the same. Realistically reconstruct the floor and walls that were hidden behind the removed items. The result must be a clean, empty, move-in-ready room: photorealistic real-estate photography, natural lighting, high detail.`;
  }
  if (modeId === "twilight") {
    return `Transform this daytime real-estate exterior photo into a professional twilight (dusk) shot. Keep the building architecture, landscaping, driveway and camera perspective exactly the same. Replace the sky with a deep blue evening sky with a warm sunset glow near the horizon. Make warm interior lighting glow through all the windows, and add subtle warm exterior and landscape lighting where fixtures exist. Professional MLS twilight photography: photorealistic, rich color, high detail.`;
  }
  if (modeId === "renovation") {
    return `Renovate this ${roomPrompt}: replace the flooring, wall finishes, cabinetry, countertops, tiling and built-in fixtures with brand-new ones in ${stylePrompt}. Keep the room's layout — walls, windows, doors, ceiling and camera perspective — exactly the same. Update furniture only where needed to complement the renovation. The result must look like a freshly completed, professionally renovated space: photorealistic interior photography, natural lighting, high detail.`;
  }
  if (modeId === "curb_appeal") {
    return `Enhance the curb appeal of this real-estate exterior photo. Keep the building architecture, structures and camera perspective exactly the same. Refresh the landscaping: lush green freshly mowed lawn, neatly trimmed hedges and bushes, tasteful flower beds, clean driveway and walkways. Tidy the facade — remove stains, dirt, clutter, trash bins and parked cars where possible — and replace the sky with a clear blue sky with soft clouds. Professional MLS real-estate photography: photorealistic, bright, inviting, high detail.`;
  }
  return `Redesign this ${roomPrompt} interior in ${stylePrompt}. Keep the room architecture — walls, windows, doors, ceiling and camera perspective — exactly the same. Replace furniture, lighting, color palette and decor to match the target style. Photorealistic interior photography, natural lighting, high detail.`;
}

export const CREDIT_PACKS: CreditPack[] = [
  {
    id: "starter",
    label: "Starter",
    credits: 50,
    price: "$9",
    usd: 9,
    perImage: "$0.18 / image",
  },
  {
    id: "pro",
    label: "Pro",
    credits: 150,
    price: "$19",
    usd: 19,
    perImage: "$0.13 / image",
    highlight: true,
  },
  {
    id: "agency",
    label: "Agency",
    credits: 500,
    price: "$49",
    usd: 49,
    perImage: "$0.10 / image",
  },
];

/** Anonymous free trial generations (tracked in localStorage + per-IP on server). */
export const FREE_GENERATIONS = 2;
/** Free credits granted once on first sign-in. */
export const SIGNUP_CREDITS = 5;
/** Per-IP daily cap for anonymous demo usage. */
export const DAILY_IP_LIMIT = 10;
